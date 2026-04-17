"""
Service Publications — accès exclusif en écriture à la table `publications`.

Toute création, mise à jour ou recherche de publication passe par ce module.
Les scripts de normalisation (HAL, OpenAlex, WoS, ScanR) et les autres
traitements appellent ces fonctions au lieu de faire du SQL direct.

Les fonctions find_by_* retournent des namedtuples pour un accès par nom
indépendant du type de curseur (tuple ou RealDictCursor).
"""

from psycopg2.extras import Json

from infrastructure.repositories.publication_repository import (
    PgPublicationRepository,
    PubByDoi,
    PubByNnt,
    PubByTitle,
    PubThesisCandidate,
)
from services.audit import emit_event
from utils.db_helpers import row_val as _val
from utils.doc_types import map_doc_type

# Re-export des namedtuples pour les call sites historiques (scripts,
# processing) qui font `from services.publications import PubByDoi`.
__all__ = [
    "PubByDoi", "PubByNnt", "PubByTitle", "PubThesisCandidate",
    # Fonctions publiques du service (ajoutées au fur et à mesure).
]


def find_by_doi(cur, doi: str) -> PubByDoi | None:
    """Cherche une publication par DOI (case-insensitive)."""
    return PgPublicationRepository(cur).find_by_doi(doi)


def find_by_nnt(cur, nnt: str) -> PubByNnt | None:
    """Cherche une publication via NNT (source_publications.external_ids)."""
    return PgPublicationRepository(cur).find_by_nnt(nnt)


def find_by_title(cur, title_normalized: str, pub_year: int, journal_id: int) -> PubByTitle | None:
    """Cherche une publication par titre normalisé + année + journal."""
    return PgPublicationRepository(cur).find_by_title(title_normalized, pub_year, journal_id)


def find_thesis_by_title(cur, title_normalized: str, pub_year: int) -> list[PubThesisCandidate]:
    """Cherche des thèses par titre normalisé + année (sans journal_id)."""
    return PgPublicationRepository(cur).find_thesis_by_title(title_normalized, pub_year)


def try_merge_by_doi(cur, pub_id: int, doi: str | None) -> int:
    """Tente de fusionner via DOI si la publication n'en a pas encore.

    Si pub_id n'a pas de DOI et qu'une autre publication porte ce DOI,
    les deux sont fusionnées (l'autre absorbe pub_id).
    Attribue le DOI à la publication si elle n'en a pas.

    Retourne le pub_id effectif (peut changer en cas de fusion).
    """
    if not doi:
        return pub_id
    repo = PgPublicationRepository(cur)
    if repo.get_doi(pub_id):
        return pub_id
    # La pub n'a pas de DOI : vérifier si une autre l'a
    existing = repo.find_by_doi(doi)
    if existing and existing.id != pub_id:
        merge_publications(cur, existing.id, pub_id)
        return existing.id
    # Attribuer le DOI
    repo.set_doi(pub_id, doi)
    return pub_id


def resolve_doi_conflict(
    cur, doi: str, doc_type: str, title_normalized: str, existing
) -> tuple[str | None, int | None]:
    """Gere les conflits de DOI entre chapitres et ouvrages.

    Quand un DOI existe deja sur une publication d'un type incompatible
    (chapitre vs ouvrage), le DOI est retire de l'un ou des deux cotes.

    Retourne (doi_corrige, publication_id_si_fusion).
    - doi_corrige : le DOI a utiliser pour le nouveau document (None si retire)
    - publication_id_si_fusion : l'id de la publication existante si fusion, None sinon
    """
    repo = PgPublicationRepository(cur)
    ex_type = existing.doc_type or ""
    chapter_types = ("book_chapter", "book-chapter", "chapter")
    book_types = ("book",)

    # Chapitre vs ouvrage : le DOI est celui de l'ouvrage, pas du chapitre
    if doc_type in chapter_types and ex_type in book_types:
        return None, None

    if doc_type in book_types and ex_type in chapter_types:
        repo.clear_doi(existing.id)
        return doi, None

    # Deux chapitres avec titres differents : DOI errone des deux cotes
    if doc_type in chapter_types and ex_type in chapter_types:
        ex_title = existing.title_normalized or ""
        if title_normalized != ex_title:
            repo.clear_doi(existing.id)
            return None, None
        return doi, existing.id

    # Cas normal : meme DOI, types compatibles -> fusion
    return doi, existing.id


def find_or_create(
    cur,
    *,
    title: str,
    title_normalized: str,
    pub_year: int,
    doc_type: str = "other",
    doi: str | None = None,
    nnt: str | None = None,
    oa_status: str = "unknown",
    journal_id: int | None = None,
    container_title: str | None = None,
    language: str | None = None,
    allow_create: bool = True,
) -> tuple[int | None, bool]:
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

    repo = PgPublicationRepository(cur)

    # 1. Chercher par DOI
    if doi:
        existing = repo.find_by_doi(doi)
        if existing:
            doi, merge_id = resolve_doi_conflict(cur, doi, doc_type, title_normalized, existing)
            if merge_id:
                return merge_id, False

    # 1b. Chercher par NNT (theses uniquement)
    if nnt:
        existing = repo.find_by_nnt(nnt)
        if existing:
            try_merge_by_doi(cur, existing.id, doi)
            return existing.id, False

    # 2. Creer
    if not allow_create:
        return None, False

    pub_id = repo.create(
        title=title, title_normalized=title_normalized,
        doc_type=doc_type, pub_year=pub_year, doi=doi,
        oa_status=oa_status, journal_id=journal_id,
        container_title=container_title, language=language,
    )
    return pub_id, True


def update_oa_status(cur, pub_id: int, oa_status: str) -> None:
    """Met à jour le statut OA d'une publication."""
    PgPublicationRepository(cur).update_oa_status(pub_id, oa_status)


def update_countries(cur, pub_id: int, countries: list[str]) -> None:
    """Met à jour les pays d'une publication."""
    PgPublicationRepository(cur).update_countries(pub_id, countries)


def update_sources(cur, pub_id: int) -> None:
    """Recalcule publications.sources depuis source_publications."""
    PgPublicationRepository(cur).update_sources(pub_id)


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
    "diamond": 7,
    "gold": 6,
    "hybrid": 5,
    "bronze": 4,
    "green": 3,
    "closed": 2,
    "unknown": 1,
}


def refresh_from_sources(cur, pub_id: int) -> None:  # noqa: C901
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
    • JSONB biblio, meta : fusion shallow par clé (clés généralement
      orthogonales entre sources) ; en cas de conflit sur une clé, la
      source prioritaire l'emporte.
    • JSONB topics : composite par source — {"openalex": [...], "theses":
      {...}, "scanr": ...}. Chaque source garde sa forme native (liste
      hiérarchique ou dict selon la source) pour ne rien perdre.

    Ne touche PAS à : title, title_normalized, notes, sources (utiliser
    update_sources() séparément).
    """
    # Utiliser un RealDictCursor pour accès par nom de colonne,
    # quel que soit le type de curseur passé par l'appelant.
    from psycopg2.extras import RealDictCursor

    dict_cur = cur.connection.cursor(cursor_factory=RealDictCursor)
    dict_cur.execute(
        """
        SELECT source, doi, doc_type, pub_year, journal_id, oa_status,
               container_title, language, abstract, keywords, countries,
               topics, biblio, meta, is_retracted, external_ids
        FROM source_publications
        WHERE publication_id = %s
    """,
        (pub_id,),
    )
    rows = dict_cur.fetchall()
    dict_cur.close()
    if not rows:
        return

    # Déterminer si c'est une thèse et si un OA pointe vers HAL
    has_hal_link = any(
        r["source"] == "openalex" and (r["external_ids"] or {}).get("hal") for r in rows
    )
    is_thesis = any(
        map_doc_type(r["doc_type"], r["source"]) in ("thesis", "ongoing_thesis") for r in rows
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
            for item in r[field] or []:
                key = item.lower() if isinstance(item, str) else item
                if key not in seen:
                    seen.add(key)
                    result.append(item)
        return result or None

    def merge_jsonb(field):
        """Fusion shallow par clé pour meta/biblio : les deux sont toujours
        des dicts avec des clés orthogonales entre sources (pas de conflit
        en pratique). La source prioritaire gagne par clé."""
        merged = {}
        for r in rows:
            d = r[field]
            if isinstance(d, dict):
                for k, v in d.items():
                    if k not in merged:
                        merged[k] = v
        return merged or None

    def topics_by_source():
        """Indexe les topics par source pour ne RIEN perdre de l'info.

        Les topics ont des schémas radicalement différents selon la source
        (liste hiérarchique OpenAlex vs dict discipline/rameau theses.fr) ;
        une fusion par clé ne peut pas les unifier sans perte. On rend
        donc `publications.topics` composite :
            {"openalex": [...], "theses": {...}, "scanr": ...}
        Chaque source garde sa forme native.
        """
        out: dict = {}
        for r in rows:
            topics = r["topics"]
            if topics:
                out[r["source"]] = topics
        return out or None

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
    new_topics = topics_by_source()
    new_biblio = merge_jsonb("biblio")
    new_meta = merge_jsonb("meta")

    cur.execute(
        """
        UPDATE publications SET
            doi = %s, doc_type = %s::doc_type, pub_year = %s,
            journal_id = %s, oa_status = %s::oa_type,
            container_title = %s, language = %s, abstract = %s,
            keywords = %s, countries = %s,
            topics = %s, biblio = %s, meta = %s,
            is_retracted = %s, updated_at = now()
        WHERE id = %s
    """,
        (
            new_doi,
            new_doc_type,
            new_pub_year,
            new_journal_id,
            new_oa_status,
            new_container_title,
            new_language,
            new_abstract,
            new_keywords,
            new_countries,
            Json(new_topics) if new_topics else None,
            Json(new_biblio) if new_biblio else None,
            Json(new_meta) if new_meta else None,
            new_is_retracted,
            pub_id,
        ),
    )

    update_sources(cur, pub_id)


def mark_distinct(cur, pub_id_a: int, pub_id_b: int) -> None:
    """Marque deux publications comme distinctes (non-doublon) dans
    `distinct_publications`. Idempotent.

    Les IDs sont triés pour garantir l'unicité de la paire.
    """
    inserted = PgPublicationRepository(cur).mark_distinct(pub_id_a, pub_id_b)
    if inserted:
        emit_event(
            cur, "publication.marked_distinct", "publication", inserted[0],
            {"other_id": inserted[1]},
        )


def merge_publications(cur, target_id: int, source_id: int) -> None:
    """Fusionne la publication source_id dans target_id.

    1. Transfère les documents sources (HAL, OA, WoS)
    2. Transfère les authorships vérité (supprime doublons)
    3. Enrichit la cible avec les métadonnées de la source
    4. Supprime la source et les distinct_publications associées
    """
    # 1. Transférer les documents sources
    cur.execute(
        "UPDATE source_publications SET publication_id = %s WHERE publication_id = %s",
        (target_id, source_id),
    )

    # 2. Transférer les authorships vérité (supprimer doublons par person_id)
    cur.execute(
        """
        DELETE FROM authorships
        WHERE publication_id = %s
          AND person_id IN (
              SELECT person_id FROM authorships WHERE publication_id = %s
          )
    """,
        (source_id, target_id),
    )
    cur.execute(
        "UPDATE authorships SET publication_id = %s WHERE publication_id = %s",
        (target_id, source_id),
    )

    # 3. Enrichir la cible avec les métadonnées de la source
    # Ordre : capturer les valeurs src → NULL-er doi src (pour libérer la
    # contrainte UNIQUE lower(doi)) → enrichir target avec les valeurs capturées.
    cur.execute(
        """
        SELECT doi, journal_id, oa_status::text AS oa_status,
               language, container_title, countries
        FROM publications WHERE id = %s
    """,
        (source_id,),
    )
    src = cur.fetchone()
    cur.execute("UPDATE publications SET doi = NULL WHERE id = %s", (source_id,))
    cur.execute(
        """
        UPDATE publications SET
            doi = COALESCE(doi, LOWER(%s)),
            journal_id = COALESCE(journal_id, %s),
            oa_status = CASE
                WHEN %s = 'diamond' THEN 'diamond'::oa_type
                WHEN oa_status IN ('unknown', 'closed')
                    AND %s NOT IN ('unknown', 'closed')
                THEN %s::oa_type ELSE oa_status END,
            language = COALESCE(language, %s),
            container_title = COALESCE(container_title, %s),
            countries = CASE
                WHEN countries IS NULL THEN %s
                WHEN %s IS NULL THEN countries
                ELSE (SELECT array_agg(DISTINCT c ORDER BY c)
                      FROM unnest(countries || %s) AS c)
                END,
            updated_at = now()
        WHERE id = %s
    """,
        (
            src["doi"], src["journal_id"],
            src["oa_status"], src["oa_status"], src["oa_status"],
            src["language"], src["container_title"],
            src["countries"], src["countries"], src["countries"],
            target_id,
        ),
    )

    # 4. Nettoyer distinct_publications et supprimer la source
    cur.execute(
        """
        DELETE FROM distinct_publications
        WHERE pub_id_a = %s OR pub_id_b = %s
    """,
        (source_id, source_id),
    )
    cur.execute("DELETE FROM publications WHERE id = %s", (source_id,))

    # 5. Recalculer les sources de la cible
    update_sources(cur, target_id)

    emit_event(
        cur, "publication.merged", "publication", target_id,
        {"source_id": source_id},
    )
