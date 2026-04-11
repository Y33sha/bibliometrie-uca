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
PubByNnt = namedtuple("PubByNnt", ["id", "doc_type", "title_normalized"])
PubByTitle = namedtuple("PubByTitle", ["id", "doi"])
PubThesisCandidate = namedtuple("PubThesisCandidate", ["id", "doi"])


def find_by_doi(cur, doi: str) -> PubByDoi | None:
    """Cherche une publication par DOI (case-insensitive)."""
    if not doi:
        return None
    cur.execute("SELECT id, doc_type, title_normalized FROM publications WHERE lower(doi) = lower(%s)", (doi,))
    row = cur.fetchone()
    return PubByDoi(_val(row, 0), _val(row, 1), _val(row, 2)) if row else None


def find_by_nnt(cur, nnt: str) -> PubByNnt | None:
    """Cherche une publication via NNT stocké dans source_documents.external_ids."""
    if not nnt:
        return None
    cur.execute("""
        SELECT p.id, p.doc_type, p.title_normalized
        FROM publications p
        JOIN source_documents sd ON sd.publication_id = p.id
        WHERE sd.external_ids->>'nnt' = %s
        LIMIT 1
    """, (nnt.upper(),))
    row = cur.fetchone()
    return PubByNnt(_val(row, 0), _val(row, 1), _val(row, 2)) if row else None


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


def find_thesis_by_title(cur, title_normalized: str, pub_year: int) -> list[PubThesisCandidate]:
    """Cherche des thèses par titre normalisé + année.

    Retourne les candidats pour déduplication thesis-specific
    (pas de journal_id, donc le tier 2 standard ne fonctionne pas).
    """
    if not title_normalized or not pub_year:
        return []
    cur.execute("""
        SELECT id, doi FROM publications
        WHERE title_normalized = %s AND pub_year = %s
          AND doc_type IN ('thesis', 'ongoing_thesis')
        ORDER BY id
    """, (title_normalized, pub_year))
    rows = cur.fetchall()
    return [PubThesisCandidate(_val(row, 0), _val(row, 1)) for row in rows]


def _enrich(cur, pub_id: int, *, doi: str | None = None,
            doc_type: str | None = None, journal_id: int | None = None,
            oa_status: str | None = None, container_title: str | None = None,
            language: str | None = None) -> int:
    """Enrichit une publication existante avec des metadonnees complementaires.

    Regles de priorite (ne jamais degrader) :
    - DOI : ne remplace pas un DOI existant
    - doc_type : 'other' peut etre remplace par un type plus precis
    - oa_status : 'green' gagne sur 'closed'/'unknown', 'diamond' gagne sur tout
    - journal_id, container_title, language : COALESCE (premier arrive gagne)

    Si le DOI est deja pris par une autre publication, les deux sont fusionnees.
    Retourne le pub_id effectif (peut changer en cas de fusion).
    """
    # Si on veut attribuer un DOI, verifier qu'il n'est pas deja pris
    if doi:
        cur.execute("SELECT doi FROM publications WHERE id = %s", (pub_id,))
        row = cur.fetchone()
        current_doi = row["doi"] if isinstance(row, dict) else row[0] if row else None
        if row and not current_doi:
            existing = find_by_doi(cur, doi)
            if existing and existing.id != pub_id:
                # Le DOI est deja sur une autre publication -> fusionner
                merge_publications(cur, existing.id, pub_id)
                pub_id = existing.id

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
    return pub_id


def resolve_doi_conflict(cur, doi: str, doc_type: str, title_normalized: str,
                         existing) -> tuple[str | None, int | None]:
    """Gere les conflits de DOI entre chapitres et ouvrages.

    Quand un DOI existe deja sur une publication d'un type incompatible
    (chapitre vs ouvrage), le DOI est retire de l'un ou des deux cotes.

    Retourne (doi_corrige, publication_id_si_fusion).
    - doi_corrige : le DOI a utiliser pour le nouveau document (None si retire)
    - publication_id_si_fusion : l'id de la publication existante si fusion, None sinon
    """
    ex_type = existing.doc_type or ""
    chapter_types = ("book_chapter", "book-chapter", "chapter")
    book_types = ("book",)

    # Chapitre vs ouvrage : le DOI est celui de l'ouvrage, pas du chapitre
    if doc_type in chapter_types and ex_type in book_types:
        return None, None

    if doc_type in book_types and ex_type in chapter_types:
        cur.execute("UPDATE publications SET doi = NULL, updated_at = now() WHERE id = %s",
                    (existing.id,))
        return doi, None

    # Deux chapitres avec titres differents : DOI errone des deux cotes
    if doc_type in chapter_types and ex_type in chapter_types:
        ex_title = existing.title_normalized or ""
        if title_normalized != ex_title:
            cur.execute("UPDATE publications SET doi = NULL, updated_at = now() WHERE id = %s",
                        (existing.id,))
            return None, None
        else:
            return doi, existing.id

    # Cas normal : meme DOI, types compatibles -> fusion
    return doi, existing.id


def find_or_create(cur, *, title: str, title_normalized: str,
                   pub_year: int, doc_type: str = "other",
                   doi: str | None = None,
                   nnt: str | None = None,
                   oa_status: str = "unknown",
                   journal_id: int | None = None,
                   container_title: str | None = None,
                   language: str | None = None,
                   allow_create: bool = True) -> tuple[int | None, bool]:
    """Trouve ou cree une publication.

    Logique de deduplication par identifiant unique :
    1. Par DOI (case-insensitive)
    1b. Par NNT (via source_documents.external_ids, theses uniquement)
    2. Creation

    Retourne (publication_id, is_new).
    Si allow_create=False et aucune publication trouvee, retourne (None, False).
    """
    if not pub_year or not title:
        return None, False

    # 1. Chercher par DOI
    if doi:
        existing = find_by_doi(cur, doi)
        if existing:
            doi, merge_id = resolve_doi_conflict(
                cur, doi, doc_type, title_normalized, existing)
            if merge_id:
                _enrich(cur, merge_id, doi=doi, doc_type=doc_type,
                        journal_id=journal_id, oa_status=oa_status,
                        container_title=container_title, language=language)
                return merge_id, False

    # 1b. Chercher par NNT (theses uniquement)
    if nnt:
        existing = find_by_nnt(cur, nnt)
        if existing:
            _enrich(cur, existing.id, doi=doi, doc_type=doc_type,
                    journal_id=journal_id, oa_status=oa_status,
                    container_title=container_title, language=language)
            return existing.id, False

    # 2. Creer
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


def update_sources(cur, pub_id: int):
    """Recalcule publications.sources depuis source_documents."""
    cur.execute("""
        UPDATE publications SET sources = COALESCE(sub.srcs, '{}'), updated_at = now()
        FROM (
            SELECT array_agg(DISTINCT source::source_type ORDER BY source::source_type) AS srcs
            FROM source_documents
            WHERE publication_id = %s
        ) sub
        WHERE id = %s
    """, (pub_id, pub_id))


def merge_publications(cur, target_id: int, source_id: int):
    """Fusionne la publication source_id dans target_id.

    1. Transfère les documents sources (HAL, OA, WoS)
    2. Transfère les authorships vérité (supprime doublons)
    3. Enrichit la cible avec les métadonnées de la source
    4. Supprime la source et les distinct_publications associées
    """
    # 1. Transférer les documents sources
    cur.execute("UPDATE source_documents SET publication_id = %s WHERE publication_id = %s",
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

    # 5. Recalculer les sources de la cible
    update_sources(cur, target_id)
