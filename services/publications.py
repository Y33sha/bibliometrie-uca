"""
Service Publications — accès exclusif en écriture à la table `publications`.

Toute création, mise à jour ou recherche de publication passe par ce module.
Les scripts de normalisation (HAL, OpenAlex, WoS, ScanR) et les autres
traitements appellent ces fonctions au lieu de faire du SQL direct.

Les fonctions find_by_* retournent des namedtuples pour un accès par nom
indépendant du type de curseur (tuple ou RealDictCursor).
"""

from collections import namedtuple

from psycopg2.extras import Json

from utils.db_helpers import row_val as _val
from utils.doc_types import map_doc_type

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
    """Cherche une publication via NNT stocké dans source_publications.external_ids."""
    if not nnt:
        return None
    cur.execute("""
        SELECT p.id, p.doc_type, p.title_normalized
        FROM publications p
        JOIN source_publications sd ON sd.publication_id = p.id
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


def try_merge_by_doi(cur, pub_id: int, doi: str | None) -> int:
    """Tente de fusionner via DOI si la publication n'en a pas encore.

    Si pub_id n'a pas de DOI et qu'une autre publication porte ce DOI,
    les deux sont fusionnées (l'autre absorbe pub_id).
    Attribue le DOI à la publication si elle n'en a pas.

    Retourne le pub_id effectif (peut changer en cas de fusion).
    """
    if not doi:
        return pub_id
    cur.execute("SELECT doi FROM publications WHERE id = %s", (pub_id,))
    row = cur.fetchone()
    current_doi = row["doi"] if isinstance(row, dict) else row[0] if row else None
    if current_doi:
        return pub_id
    # La pub n'a pas de DOI : vérifier si une autre l'a
    existing = find_by_doi(cur, doi)
    if existing and existing.id != pub_id:
        merge_publications(cur, existing.id, pub_id)
        return existing.id
    # Attribuer le DOI
    cur.execute("UPDATE publications SET doi = %s, updated_at = now() WHERE id = %s",
                (doi, pub_id))
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
    1b. Par NNT (via source_publications.external_ids, theses uniquement)
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
                return merge_id, False

    # 1b. Chercher par NNT (theses uniquement)
    if nnt:
        existing = find_by_nnt(cur, nnt)
        if existing:
            try_merge_by_doi(cur, existing.id, doi)
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
    """Recalcule publications.sources depuis source_publications."""
    cur.execute("""
        UPDATE publications SET sources = COALESCE(sub.srcs, '{}'), updated_at = now()
        FROM (
            SELECT array_agg(DISTINCT source::source_type ORDER BY source::source_type) AS srcs
            FROM source_publications
            WHERE publication_id = %s
        ) sub
        WHERE id = %s
    """, (pub_id, pub_id))


# ── Recalcul complet des métadonnées depuis les source_publications ──────

# Ordre de priorité des sources pour les champs scalaires.
# Pour les thèses, theses.fr est toujours prioritaire.
# Cas particulier : si un document OpenAlex référence un HAL-ID
# (external_ids->>'hal'), HAL passe devant theses.fr même pour les thèses.
_PRIORITY_THESIS = ["theses", "hal", "openalex", "wos", "scanr"]
_PRIORITY_DEFAULT = ["hal", "openalex", "wos", "scanr", "theses"]
_PRIORITY_THESIS_HAL_LINKED = ["hal", "theses", "openalex", "wos", "scanr"]

# Classement des statuts OA : le plus ouvert gagne.
_OA_RANK = {
    "diamond": 7, "gold": 6, "hybrid": 5, "bronze": 4,
    "green": 3, "closed": 2, "unknown": 1,
}


def refresh_from_sources(cur, pub_id: int):
    """Recalcule les métadonnées d'une publication depuis ses source_publications.

    Contrairement à l'ancien _enrich() qui faisait du COALESCE incrémental (premier arrivé
    gagne, jamais de downgrade), cette fonction fait un recalcul complet :
    elle lit TOUS les source_publications attachés et réapplique les règles de
    priorité depuis zéro. Elle peut donc corriger des métadonnées obsolètes
    (ex: ongoing_thesis → thesis après soutenance).

    Règles de priorité entre sources :
    ─────────────────────────────────
    • Thèses (doc_type thesis/ongoing_thesis) : theses.fr > HAL > OA > WoS > ScanR
    • Autres publications :                      HAL > OA > WoS > ScanR > theses.fr
    • Si un document OpenAlex référence un HAL-ID (external_ids->>'hal'),
      HAL passe prioritaire même pour les thèses.

    Règles de fusion par type de champ :
    ────────────────────────────────────
    • Scalaires (doi, doc_type, pub_year, journal_id, container_title, language) :
      premier non-null dans l'ordre de priorité.
    • Texte (abstract) : idem, premier non-null.
    • oa_status : le statut le plus ouvert parmi toutes les sources
      (diamond > gold > hybrid > bronze > green > closed > unknown).
    • Booléen (is_retracted) : True si au moins une source le dit.
    • Listes (keywords, countries) : union de toutes les sources, dédupliquée.
    • JSONB (topics, biblio, meta) : fusion des clés de toutes les sources ;
      en cas de conflit sur une clé, la source prioritaire l'emporte.

    Ne touche PAS à : title, title_normalized, notes, sources (utiliser
    update_sources() séparément).
    """
    # Utiliser un RealDictCursor pour accès par nom de colonne,
    # quel que soit le type de curseur passé par l'appelant.
    from psycopg2.extras import RealDictCursor
    dict_cur = cur.connection.cursor(cursor_factory=RealDictCursor)
    dict_cur.execute("""
        SELECT source, doi, doc_type, pub_year, journal_id, oa_status,
               container_title, language, abstract, keywords, countries,
               topics, biblio, meta, is_retracted, external_ids
        FROM source_publications
        WHERE publication_id = %s
    """, (pub_id,))
    rows = dict_cur.fetchall()
    dict_cur.close()
    if not rows:
        return

    # Déterminer si c'est une thèse et si un OA pointe vers HAL
    has_hal_link = any(
        r["source"] == "openalex"
        and (r["external_ids"] or {}).get("hal")
        for r in rows
    )
    is_thesis = any(
        map_doc_type(r["doc_type"], r["source"]) in ("thesis", "ongoing_thesis")
        for r in rows
    )

    if is_thesis and has_hal_link:
        priority = _PRIORITY_THESIS_HAL_LINKED
    elif is_thesis:
        priority = _PRIORITY_THESIS
    else:
        priority = _PRIORITY_DEFAULT

    # Trier les lignes par priorité de source
    rank = {s: i for i, s in enumerate(priority)}
    rows.sort(key=lambda r: rank.get(r["source"], 99))

    # --- Helpers ---
    def first_non_null(field):
        for r in rows:
            v = r[field]
            if v is not None:
                return v
        return None

    def merge_lists(field):
        seen = set()
        result = []
        for r in rows:
            for item in (r[field] or []):
                key = item.lower() if isinstance(item, str) else item
                if key not in seen:
                    seen.add(key)
                    result.append(item)
        return result or None

    def merge_jsonb(field):
        merged = {}
        for r in rows:
            d = r[field]
            if isinstance(d, dict):
                for k, v in d.items():
                    if k not in merged:
                        merged[k] = v
        return merged or None

    def best_oa_status():
        best, best_rank = None, 0
        for r in rows:
            s = r["oa_status"]
            if s and _OA_RANK.get(s, 0) > best_rank:
                best, best_rank = s, _OA_RANK[s]
        return best

    # --- Calcul des valeurs ---
    new_doi = first_non_null("doi")
    # doc_type : premier non-null mappé vers l'enum canonique
    new_doc_type = "other"
    for r in rows:
        if r["doc_type"]:
            new_doc_type = map_doc_type(r["doc_type"], r["source"])
            break
    new_pub_year = first_non_null("pub_year")
    new_journal_id = first_non_null("journal_id")
    new_container_title = first_non_null("container_title")
    new_language = first_non_null("language")
    new_abstract = first_non_null("abstract")
    new_oa_status = best_oa_status()
    new_is_retracted = any(r["is_retracted"] for r in rows if r["is_retracted"])
    new_keywords = merge_lists("keywords")
    new_countries = merge_lists("countries")
    new_topics = merge_jsonb("topics")
    new_biblio = merge_jsonb("biblio")
    new_meta = merge_jsonb("meta")

    cur.execute("""
        UPDATE publications SET
            doi = %s, doc_type = %s::doc_type, pub_year = %s,
            journal_id = %s, oa_status = %s::oa_type,
            container_title = %s, language = %s, abstract = %s,
            keywords = %s, countries = %s,
            topics = %s, biblio = %s, meta = %s,
            is_retracted = %s, updated_at = now()
        WHERE id = %s
    """, (new_doi, new_doc_type, new_pub_year,
          new_journal_id, new_oa_status,
          new_container_title, new_language, new_abstract,
          new_keywords, new_countries,
          Json(new_topics) if new_topics else None,
          Json(new_biblio) if new_biblio else None,
          Json(new_meta) if new_meta else None,
          new_is_retracted, pub_id))

    update_sources(cur, pub_id)


def merge_publications(cur, target_id: int, source_id: int):
    """Fusionne la publication source_id dans target_id.

    1. Transfère les documents sources (HAL, OA, WoS)
    2. Transfère les authorships vérité (supprime doublons)
    3. Enrichit la cible avec les métadonnées de la source
    4. Supprime la source et les distinct_publications associées
    """
    # 1. Transférer les documents sources
    cur.execute("UPDATE source_publications SET publication_id = %s WHERE publication_id = %s",
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
