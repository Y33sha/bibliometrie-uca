"""
Service Publications — accès exclusif en écriture à la table `publications`.

Toute création, mise à jour ou recherche de publication passe par ce module.
Les scripts de normalisation (HAL, OpenAlex, WoS, ScanR) et les autres
traitements appellent ces fonctions au lieu de faire du SQL direct.

Les fonctions find_by_* retournent des namedtuples pour un accès par nom
indépendant du type de curseur (tuple ou RealDictCursor).
"""

from typing import Any

from application.audit import emit_event
from domain.doc_types import map_doc_type
from domain.ports.publication_repository import PublicationRepository
from domain.publication import (
    PubByDoi,
    PubByNnt,
    PubByTitle,
    PubThesisCandidate,
)

# Re-export des namedtuples pour les call sites historiques (scripts,
# processing) qui font `from application.publications import PubByDoi`.
__all__ = [
    "PubByDoi",
    "PubByNnt",
    "PubByTitle",
    "PubThesisCandidate",
    # Fonctions publiques du service (ajoutées au fur et à mesure).
]


def find_by_doi(cur: Any, doi: str, *, repo: PublicationRepository) -> PubByDoi | None:
    """Cherche une publication par DOI (case-insensitive)."""
    return repo.find_by_doi(doi)


def find_by_nnt(cur: Any, nnt: str, *, repo: PublicationRepository) -> PubByNnt | None:
    """Cherche une publication via NNT (source_publications.external_ids)."""
    return repo.find_by_nnt(nnt)


def find_by_title(
    cur: Any,
    title_normalized: str,
    pub_year: int,
    journal_id: int,
    *,
    repo: PublicationRepository,
) -> PubByTitle | None:
    """Cherche une publication par titre normalisé + année + journal."""
    return repo.find_by_title(title_normalized, pub_year, journal_id)


def find_thesis_by_title(
    cur: Any,
    title_normalized: str,
    pub_year: int,
    *,
    repo: PublicationRepository,
) -> list[PubThesisCandidate]:
    """Cherche des thèses par titre normalisé + année (sans journal_id)."""
    return repo.find_thesis_by_title(title_normalized, pub_year)


def try_merge_by_doi(
    cur: Any, pub_id: int, doi: str | None, *, repo: PublicationRepository
) -> int:
    """Tente de fusionner via DOI si la publication n'en a pas encore.

    Si pub_id n'a pas de DOI et qu'une autre publication porte ce DOI,
    les deux sont fusionnées (l'autre absorbe pub_id).
    Attribue le DOI à la publication si elle n'en a pas.

    Retourne le pub_id effectif (peut changer en cas de fusion).
    """
    if not doi:
        return pub_id
    if repo.get_doi(pub_id):
        return pub_id
    # La pub n'a pas de DOI : vérifier si une autre l'a
    existing = repo.find_by_doi(doi)
    if existing and existing.id != pub_id:
        merge_publications(cur, existing.id, pub_id, repo=repo)
        return existing.id
    # Attribuer le DOI
    repo.set_doi(pub_id, doi)
    return pub_id


def resolve_doi_conflict(
    cur: Any,
    doi: str,
    doc_type: str,
    title_normalized: str,
    existing: Any,
    *,
    repo: PublicationRepository,
) -> tuple[str | None, int | None]:
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
    cur: Any,
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
    repo: PublicationRepository,
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

    # 1. Chercher par DOI
    if doi:
        existing = repo.find_by_doi(doi)
        if existing:
            doi, merge_id = resolve_doi_conflict(
                cur, doi, doc_type, title_normalized, existing, repo=repo
            )
            if merge_id:
                return merge_id, False

    # 1b. Chercher par NNT (theses uniquement)
    if nnt:
        existing_nnt = repo.find_by_nnt(nnt)
        if existing_nnt:
            try_merge_by_doi(cur, existing_nnt.id, doi, repo=repo)
            return existing_nnt.id, False

    # 2. Creer
    if not allow_create:
        return None, False

    pub_id = repo.create(
        title=title,
        title_normalized=title_normalized,
        doc_type=doc_type,
        pub_year=pub_year,
        doi=doi,
        oa_status=oa_status,
        journal_id=journal_id,
        container_title=container_title,
        language=language,
    )
    return pub_id, True


def update_oa_status(
    cur: Any, pub_id: int, oa_status: str, *, repo: PublicationRepository
) -> None:
    """Met à jour le statut OA d'une publication."""
    repo.update_oa_status(pub_id, oa_status)


def update_countries(
    cur: Any, pub_id: int, countries: list[str], *, repo: PublicationRepository
) -> None:
    """Met à jour les pays d'une publication."""
    repo.update_countries(pub_id, countries)


def update_sources(cur: Any, pub_id: int, *, repo: PublicationRepository) -> None:
    """Recalcule publications.sources depuis source_publications."""
    repo.update_sources(pub_id)


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


def _choose_priority(rows: list[dict[str, Any]]) -> list[str]:
    """Sélectionne l'ordre de priorité des sources selon le contexte.

    - Thèses avec un OpenAlex liant vers HAL : ordre HAL-linked
    - Thèses : theses.fr > HAL > OA > WoS > ScanR
    - Autres : HAL > OA > WoS > ScanR > theses.fr
    """
    has_hal_link = any(
        r["source"] == "openalex" and (r["external_ids"] or {}).get("hal") for r in rows
    )
    is_thesis = any(
        map_doc_type(r["doc_type"], r["source"]) in ("thesis", "ongoing_thesis") for r in rows
    )
    if is_thesis and has_hal_link:
        return _PRIORITY_THESIS_HAL_LINKED
    if is_thesis:
        return _PRIORITY_THESIS
    return _PRIORITY_DEFAULT


def _first_non_null(rows: list[dict[str, Any]], field: str) -> Any:
    for r in rows:
        v = r[field]
        if v is not None:
            return v
    return None


def _merge_lists(rows: list[dict[str, Any]], field: str) -> list[Any] | None:
    seen: set[Any] = set()
    result: list[Any] = []
    for r in rows:
        for item in r[field] or []:
            key = item.lower() if isinstance(item, str) else item
            if key not in seen:
                seen.add(key)
                result.append(item)
    return result or None


def _merge_jsonb(rows: list[dict[str, Any]], field: str) -> dict | None:
    """Fusion shallow par clé pour meta/biblio (source prioritaire gagne par clé)."""
    merged: dict[str, Any] = {}
    for r in rows:
        d = r[field]
        if isinstance(d, dict):
            for k, v in d.items():
                if k not in merged:
                    merged[k] = v
    return merged or None


def _topics_by_source(rows: list[dict[str, Any]]) -> dict | None:
    """Indexe les topics par source (schémas radicalement différents par source)."""
    out: dict[str, Any] = {}
    for r in rows:
        topics = r["topics"]
        if topics:
            out[r["source"]] = topics
    return out or None


def _best_oa_status(rows: list[dict[str, Any]]) -> str | None:
    best: str | None = None
    best_rank = 0
    for r in rows:
        s = r["oa_status"]
        if s and _OA_RANK.get(s, 0) > best_rank:
            best, best_rank = s, _OA_RANK[s]
    return best


def _first_doc_type(rows: list[dict[str, Any]]) -> str:
    for r in rows:
        if r["doc_type"]:
            return map_doc_type(r["doc_type"], r["source"])
    return "other"


def refresh_from_sources(cur: Any, pub_id: int, *, repo: PublicationRepository) -> None:
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
    rows = repo.get_source_rows(pub_id)
    if not rows:
        return

    priority = _choose_priority(rows)
    rank = {s: i for i, s in enumerate(priority)}
    rows.sort(key=lambda r: rank.get(r["source"], 99))

    repo.update_aggregated(
        pub_id,
        doi=_first_non_null(rows, "doi"),
        doc_type=_first_doc_type(rows),
        pub_year=_first_non_null(rows, "pub_year"),
        journal_id=_first_non_null(rows, "journal_id"),
        oa_status=_best_oa_status(rows),
        container_title=_first_non_null(rows, "container_title"),
        language=_first_non_null(rows, "language"),
        abstract=_first_non_null(rows, "abstract"),
        keywords=_merge_lists(rows, "keywords"),
        countries=_merge_lists(rows, "countries"),
        topics=_topics_by_source(rows),
        biblio=_merge_jsonb(rows, "biblio"),
        meta=_merge_jsonb(rows, "meta"),
        is_retracted=any(r["is_retracted"] for r in rows if r["is_retracted"]),
    )
    repo.update_sources(pub_id)


def mark_distinct(
    cur: Any, pub_id_a: int, pub_id_b: int, *, repo: PublicationRepository
) -> None:
    """Marque deux publications comme distinctes (non-doublon) dans
    `distinct_publications`. Idempotent.

    Les IDs sont triés pour garantir l'unicité de la paire.
    """
    inserted = repo.mark_distinct(pub_id_a, pub_id_b)
    if inserted:
        emit_event(
            cur,
            "publication.marked_distinct",
            "publication",
            inserted[0],
            {"other_id": inserted[1]},
        )


def merge_publications(
    cur: Any, target_id: int, source_id: int, *, repo: PublicationRepository
) -> None:
    """Fusionne la publication `source_id` dans `target_id`.

    Orchestration :
    1. Délègue la séquence de transferts/suppressions au repository
    2. Recalcule le tableau `sources` de la cible
    3. Émet l'événement d'audit (silencieusement no-op hors contexte HTTP)
    """
    repo.merge_into(target_id, source_id)
    repo.update_sources(target_id)
    emit_event(
        cur,
        "publication.merged",
        "publication",
        target_id,
        {"source_id": source_id},
    )
