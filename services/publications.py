"""
Service Publications — accès exclusif en écriture à la table `publications`.

Toute création, mise à jour ou recherche de publication passe par ce module.
Les scripts de normalisation (HAL, OpenAlex, WoS, ScanR) et les autres
traitements appellent ces fonctions au lieu de faire du SQL direct.

Les fonctions find_by_* retournent des namedtuples pour un accès par nom
indépendant du type de curseur (tuple ou RealDictCursor).
"""

from collections import namedtuple
from utils.db_helpers import row_val as _val

PubByDoi = namedtuple("PubByDoi", ["id", "doc_type", "title_normalized"])
PubByTitle = namedtuple("PubByTitle", ["id", "doi"])


def find_by_doi(cur, doi: str) -> PubByDoi | None:
    """Cherche une publication par DOI (case-insensitive)."""
    if not doi:
        return None
    cur.execute("SELECT id, doc_type, title_normalized FROM publications WHERE lower(doi) = lower(%s)", (doi,))
    row = cur.fetchone()
    return PubByDoi(_val(row, 0), _val(row, 1), _val(row, 2)) if row else None


def find_by_title(cur, title_normalized: str, pub_year: int, journal_id: int) -> PubByTitle | None:
    """Cherche une publication par titre normalisé + année + journal.
    Ne matche que les articles avec journal connu (aucun NULL dans les critères).
    """
    if not title_normalized or not journal_id:
        return None
    cur.execute("""
        SELECT id, doi FROM publications
        WHERE title_normalized = %s AND pub_year = %s AND journal_id = %s
        LIMIT 1
    """, (title_normalized, pub_year, journal_id))
    row = cur.fetchone()
    return PubByTitle(_val(row, 0), _val(row, 1)) if row else None


def _enrich(cur, pub_id: int, *, doi: str | None = None,
            doc_type: str | None = None, journal_id: int | None = None,
            oa_status: str | None = None, container_title: str | None = None,
            language: str | None = None):
    """Enrichit une publication existante avec des métadonnées complémentaires.

    Règles de priorité (ne jamais dégrader) :
    - DOI : ne remplace pas un DOI existant
    - doc_type : 'other' peut être remplacé par un type plus précis
    - oa_status : 'green' gagne sur 'closed'/'unknown', 'diamond' gagne sur tout
    - journal_id, container_title, language : COALESCE (premier arrivé gagne)
    """
    cur.execute("""
        UPDATE publications SET
            doi = CASE
                WHEN publications.doi IS NOT NULL THEN publications.doi
                ELSE %s
            END,
            journal_id = COALESCE(%s, publications.journal_id),
            doc_type = CASE
                WHEN publications.doc_type = 'other' AND %s IS NOT NULL AND %s != 'other'
                    THEN %s::doc_type
                ELSE COALESCE(publications.doc_type, %s::doc_type)
            END,
            oa_status = CASE
                WHEN %s = 'green' AND publications.oa_status IN ('closed', 'unknown')
                    THEN 'green'::oa_type
                WHEN %s = 'diamond'
                    THEN 'diamond'::oa_type
                WHEN publications.oa_status = 'unknown' AND %s IS NOT NULL
                    THEN %s::oa_type
                ELSE publications.oa_status
            END,
            container_title = COALESCE(%s, publications.container_title),
            language = COALESCE(%s, publications.language),
            updated_at = now()
        WHERE id = %s
    """, (doi,
          journal_id,
          doc_type, doc_type, doc_type, doc_type,
          oa_status, oa_status, oa_status, oa_status,
          container_title,
          language,
          pub_id))


def find_or_create(cur, *, title: str, title_normalized: str,
                   pub_year: int, doc_type: str = "other",
                   doi: str | None = None,
                   oa_status: str = "unknown",
                   journal_id: int | None = None,
                   container_title: str | None = None,
                   language: str | None = None,
                   allow_create: bool = True) -> tuple[int | None, bool]:
    """Trouve ou crée une publication.

    Logique de déduplication :
    1. Par DOI (case-insensitive)
    2. Par titre normalisé + année + journal (articles uniquement)
    3. Création

    Retourne (publication_id, is_new).
    Si allow_create=False et aucune publication trouvée, retourne (None, False).
    """
    if not pub_year or not title:
        return None, False

    # 1. Chercher par DOI
    if doi:
        existing = find_by_doi(cur, doi)
        if existing:
            ex_type = existing.doc_type or ""
            ex_title = existing.title_normalized or ""
            chapter_types = ("book_chapter", "book-chapter", "chapter")
            book_types = ("book",)

            # Cas chapitre vs ouvrage : le DOI est celui de l'ouvrage,
            # pas du chapitre → on le retire du chapitre, pas de fusion
            if doc_type in chapter_types and ex_type in book_types:
                # Le nouveau est un chapitre, l'existant est un ouvrage → skip
                doi = None  # ne pas attribuer ce DOI au chapitre
            elif doc_type in book_types and ex_type in chapter_types:
                # Le nouveau est un ouvrage, l'existant est un chapitre → retirer le DOI du chapitre
                cur.execute("UPDATE publications SET doi = NULL, updated_at = now() WHERE id = %s", (existing.id,))
                # On ne fusionne pas, on continue (création ou match titre)
            elif doc_type in chapter_types and ex_type in chapter_types:
                # Deux chapitres : fusionner seulement si même titre normalisé
                if title_normalized != ex_title:
                    # Titres différents → DOI erroné, le retirer partout
                    cur.execute("UPDATE publications SET doi = NULL, updated_at = now() WHERE id = %s", (existing.id,))
                    doi = None
                else:
                    # Même titre → vraie fusion
                    _enrich(cur, existing.id, doi=doi, doc_type=doc_type,
                            journal_id=journal_id, oa_status=oa_status,
                            container_title=container_title, language=language)
                    return existing.id, False
            else:
                # Cas normal (articles, etc.) → fusion standard
                _enrich(cur, existing.id, doi=doi, doc_type=doc_type,
                        journal_id=journal_id, oa_status=oa_status,
                        container_title=container_title, language=language)
                return existing.id, False

    # 2. Chercher par titre + année + journal (articles uniquement)
    if doc_type == "article" and journal_id:
        existing = find_by_title(cur, title_normalized, pub_year, journal_id)
        if existing:
            ex_doi = existing.doi
            # Ne pas fusionner si les deux ont un DOI différent
            if doi and ex_doi and doi.lower() != ex_doi.lower():
                pass  # DOI contradictoires → ne pas fusionner
            else:
                _enrich(cur, existing.id, doi=doi, doc_type=doc_type,
                        journal_id=journal_id, oa_status=oa_status,
                        container_title=container_title, language=language)
                return existing.id, False

    # 3. Créer
    if not allow_create:
        return None, False

    cur.execute("""
        INSERT INTO publications
            (title, title_normalized, doc_type, pub_year, doi,
             oa_status, journal_id, container_title, language)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (title, title_normalized, doc_type, pub_year, doi,
          oa_status, journal_id, container_title, language))
    return _val(cur.fetchone(), 0), True


def update_oa_status(cur, pub_id: int, oa_status: str):
    """Met à jour le statut OA d'une publication."""
    cur.execute("""
        UPDATE publications SET oa_status = %s::oa_type, updated_at = now()
        WHERE id = %s
    """, (oa_status, pub_id))


def update_countries(cur, pub_id: int, countries: list[str]):
    """Met à jour les pays d'une publication."""
    cur.execute("""
        UPDATE publications SET countries = %s, updated_at = now()
        WHERE id = %s
    """, (countries, pub_id))


def merge_publications(cur, target_id: int, source_id: int):
    """Fusionne la publication source_id dans target_id.

    1. Transfère les documents sources (HAL, OA, WoS)
    2. Transfère les authorships vérité (supprime doublons)
    3. Enrichit la cible avec les métadonnées de la source
    4. Supprime la source et les distinct_publications associées
    """
    # 1. Transférer les documents sources
    for tbl in ("hal_documents", "openalex_documents", "wos_documents"):
        cur.execute(f"UPDATE {tbl} SET publication_id = %s WHERE publication_id = %s",
                    (target_id, source_id))

    # 2. Transférer les authorships vérité (supprimer doublons par person_id)
    cur.execute("""
        DELETE FROM authorships
        WHERE publication_id = %s
          AND person_id IN (
              SELECT person_id FROM authorships WHERE publication_id = %s
          )
    """, (source_id, target_id))
    cur.execute("UPDATE authorships SET publication_id = %s WHERE publication_id = %s",
                (target_id, source_id))

    # 3. Enrichir la cible avec les métadonnées de la source
    cur.execute("""
        UPDATE publications dest SET
            doi = CASE
                WHEN dest.doi IS NOT NULL THEN dest.doi
                WHEN src.doi IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM publications p2
                    WHERE LOWER(p2.doi) = LOWER(src.doi) AND p2.id <> dest.id
                ) THEN LOWER(src.doi)
                ELSE dest.doi END,
            journal_id = COALESCE(dest.journal_id, src.journal_id),
            oa_status = CASE
                WHEN src.oa_status = 'diamond' THEN 'diamond'
                WHEN dest.oa_status IN ('unknown', 'closed')
                    AND src.oa_status NOT IN ('unknown', 'closed')
                THEN src.oa_status ELSE dest.oa_status END,
            language = COALESCE(dest.language, src.language),
            container_title = COALESCE(dest.container_title, src.container_title),
            countries = CASE
                WHEN dest.countries IS NULL THEN src.countries
                WHEN src.countries IS NULL THEN dest.countries
                ELSE (SELECT array_agg(DISTINCT c ORDER BY c)
                      FROM unnest(dest.countries || src.countries) AS c)
                END,
            updated_at = now()
        FROM publications src
        WHERE dest.id = %s AND src.id = %s
    """, (target_id, source_id))

    # 4. Nettoyer distinct_publications et supprimer la source
    cur.execute("""
        DELETE FROM distinct_publications
        WHERE pub_id_a = %s OR pub_id_b = %s
    """, (source_id, source_id))
    cur.execute("DELETE FROM publications WHERE id = %s", (source_id,))
