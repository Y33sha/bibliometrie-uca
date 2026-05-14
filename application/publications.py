"""
Service Publications — accès exclusif en écriture à la table `publications`.

Toute création, mise à jour ou recherche de publication passe par ce module.
Les scripts de normalisation (HAL, OpenAlex, WoS, ScanR) et les autres
traitements appellent ces fonctions au lieu de faire du SQL direct.

Les fonctions find_by_* retournent des namedtuples pour un accès par nom
indépendant du type de curseur (tuple ou dict_row).
"""

from dataclasses import dataclass
from typing import Any

from application.audit import emit_event
from domain.errors import NotFoundError
from domain.normalize import normalize_text
from domain.ports.audit_repository import AuditRepository
from domain.ports.publication_repository import PublicationRepository
from domain.publication import (
    PubByDoi,
    PubByNnt,
    PubByTitle,
    PubThesisCandidate,
)
from domain.publications.deduplication import resolve_doi_conflict as _domain_resolve_doi_conflict
from domain.publications.doc_types import ARTICLE_SUBTYPES, map_doc_type
from domain.publications.identifiers import DOI
from domain.publications.metadata import (
    OA_STATUS_UNKNOWN_DEFAULT,
    best_oa_status,
    clean_publication_title,
)
from domain.publications.publication import Publication
from domain.sources import SOURCE_PRIORITY

# Re-export des namedtuples pour les call sites historiques (scripts,
# processing) qui font `from application.publications import PubByDoi`.
__all__ = [
    "PubByDoi",
    "PubByNnt",
    "PubByTitle",
    "PubThesisCandidate",
    # Fonctions publiques du service (ajoutées au fur et à mesure).
]


def find_by_doi(doi: str, *, repo: PublicationRepository) -> PubByDoi | None:
    """Cherche une publication par DOI (case-insensitive)."""
    return repo.find_by_doi(doi)


def find_by_nnt(nnt: str, *, repo: PublicationRepository) -> PubByNnt | None:
    """Cherche une publication via NNT (source_publications.external_ids)."""
    return repo.find_by_nnt(nnt)


def find_by_title(
    title_normalized: str,
    pub_year: int,
    journal_id: int,
    *,
    repo: PublicationRepository,
) -> PubByTitle | None:
    """Cherche une publication par titre normalisé + année + journal."""
    return repo.find_by_title(title_normalized, pub_year, journal_id)


def find_thesis_by_title(
    title_normalized: str,
    pub_year: int,
    *,
    repo: PublicationRepository,
) -> list[PubThesisCandidate]:
    """Cherche des thèses par titre normalisé + année (sans journal_id)."""
    return repo.find_thesis_by_title(title_normalized, pub_year)


def try_merge_by_doi(pub_id: int, doi: str | None, *, repo: PublicationRepository) -> int:
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
        merge_publications(existing.id, pub_id, repo=repo)
        return existing.id
    # Attribuer le DOI
    repo.set_doi(pub_id, doi)
    return pub_id


def resolve_doi_conflict(
    doi: str,
    doc_type: str,
    title_normalized: str,
    existing: PubByDoi,
    *,
    repo: PublicationRepository,
) -> tuple[str | None, int | None]:
    """Applique la règle `domain.publication.resolve_doi_conflict` et ses effets.

    Délègue la décision au domaine (fonction pure), puis réalise l'effet
    de bord `clear_doi` via le repository quand la règle le demande.

    Retourne (doi_corrige, publication_id_si_fusion).
    """
    decision = _domain_resolve_doi_conflict(
        new_doi=doi,
        new_doc_type=doc_type,
        new_title_normalized=title_normalized,
        existing_doc_type=existing.doc_type,
        existing_title_normalized=existing.title_normalized,
        existing_id=existing.id,
    )
    if decision.clear_existing_doi:
        repo.clear_doi(existing.id)
    return decision.accepted_doi, decision.merge_with_id


def publication_from_meta(meta: dict) -> Publication:
    """Adapter dict→Publication pour les call sites de `find_or_create`.

    Les normalizers (`normalize_hal`, `normalize_openalex`, etc.) construisent leur métadonnée en dict via `extract_pub_metadata`, et le dict contient à la fois les attributs d'une `Publication` ET d'autres données (`nnt`, parfois `source_doi`…) consommées par d'autres traitements en aval (`insert_*_document`, tracking de DOI rejeté). Plutôt que de fragmenter le dict côté normalizer, on convertit à l'entrée de `find_or_create`.

    Le `nnt` n'est PAS lu ici (il vit dans `source_publications.external_ids`, pas sur l'aggregate Publication). Le caller le passe séparément à `find_or_create(..., nnt=meta["nnt"])`.
    """
    return Publication(
        id=None,
        title=meta["title"],
        title_normalized=meta.get("title_normalized"),
        pub_year=meta["pub_year"],
        doc_type=meta.get("doc_type"),
        doi=DOI(meta["doi"]) if meta.get("doi") else None,
        oa_status=meta.get("oa_status"),
        journal_id=meta.get("journal_id"),
        container_title=meta.get("container_title"),
        language=meta.get("language"),
    )


def find_or_create(
    pub: Publication,
    *,
    nnt: str | None = None,
    allow_create: bool = True,
    repo: PublicationRepository,
) -> tuple[Publication | None, bool]:
    """Trouve ou crée une publication à partir d'une `Publication` candidate.

    Cascade de déduplication par identifiant unique :

    1. Par DOI (case-insensitive). En cas de collision incompatible (chapter vs book), `resolve_doi_conflict` peut décider de retirer le DOI ou de fusionner.
    2. Par NNT (via `source_publications.external_ids`, thèses uniquement). Tentative de merge tardif via DOI si la thèse trouvée n'a pas de DOI alors que `pub` en propose un.
    3. Création si `allow_create=True`.

    `pub.title` est nettoyé (décodage double-encodage HTML) avant toute comparaison ou écriture, et `pub.title_normalized` est recalculé si le titre change. La mutation a lieu sur l'instance `pub` passée.

    Le `nnt` est passé séparément car il ne vit pas sur l'aggregate `Publication` (il est stocké dans `source_publications.external_ids`).

    Retourne `(publication, is_new)` :
    - **publication trouvée** : entité hydratée depuis le repo (état canonique en base), `is_new=False`.
    - **publication créée** : la `pub` passée en entrée, mutée avec `pub.id` posé, `is_new=True`.
    - **rien trouvé et `allow_create=False`** : `(None, False)`.
    - **conflit chapter/book qui retire le DOI sans match** : `(None, False)` (le DOI est retiré, aucune match exploitable).
    """
    if not pub.has_minimal_metadata():
        return None, False

    # Décodage HTML double-encodage du titre (OpenAlex / ScanR), avant toute comparaison ou écriture.
    cleaned_title = clean_publication_title(pub.title) or ""
    if cleaned_title != pub.title:
        pub.title = cleaned_title
        pub.title_normalized = normalize_text(cleaned_title)

    # 1. Chercher par DOI
    if pub.doi is not None:
        existing = repo.find_by_doi(str(pub.doi))
        if existing:
            new_doi_str, merge_id = resolve_doi_conflict(
                str(pub.doi),
                pub.doc_type or "",
                pub.title_normalized or "",
                existing,
                repo=repo,
            )
            if merge_id is not None:
                return repo.find_by_id(merge_id), False
            # Le DOI peut avoir été invalidé par la résolution (chapter vs chapter avec titres différents).
            pub.doi = DOI(new_doi_str) if new_doi_str else None

    # 1b. Chercher par NNT (thèses uniquement)
    if nnt:
        existing_nnt = repo.find_by_nnt(nnt)
        if existing_nnt:
            try_merge_by_doi(
                existing_nnt.id,
                str(pub.doi) if pub.doi else None,
                repo=repo,
            )
            return repo.find_by_id(existing_nnt.id), False

    # 2. Créer
    if not allow_create:
        return None, False

    pub.id = repo.create(
        title=pub.title,
        title_normalized=pub.title_normalized or normalize_text(pub.title),
        doc_type=pub.doc_type or "other",
        pub_year=pub.pub_year,
        doi=str(pub.doi) if pub.doi else None,
        oa_status=pub.oa_status or OA_STATUS_UNKNOWN_DEFAULT,
        journal_id=pub.journal_id,
        container_title=pub.container_title,
        language=pub.language,
    )
    return pub, True


def update_oa_status(pub_id: int, oa_status: str, *, repo: PublicationRepository) -> None:
    """Met à jour le statut OA d'une publication."""
    repo.update_oa_status(pub_id, oa_status)


def update_countries(pub_id: int, countries: list[str], *, repo: PublicationRepository) -> None:
    """Met à jour les pays d'une publication."""
    repo.update_countries(pub_id, countries)


def update_sources(pub_id: int, *, repo: PublicationRepository) -> None:
    """Recalcule publications.sources depuis source_publications."""
    repo.update_sources(pub_id)


# ── Recalcul complet des métadonnées depuis les source_publications ──────


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


def _first_doc_type(rows: list[dict[str, Any]]) -> str:
    """Choisit le `doc_type` canonique parmi les rows ordonnées par
    `SOURCE_PRIORITY`.

    Règle générale : on prend la valeur de la source la plus prioritaire
    (premier row avec `doc_type` non-null).

    Exception « sous-types d'article » : CrossRef (priorité 2) renvoie
    `journal-article` indistinctement pour tous les types d'article (review,
    book_review, data_paper, poster, conference_paper, editorial, letter,
    erratum, retraction). Si une source moins prioritaire propose un de
    ces sous-types plus précis, on le préfère pour ne pas perdre
    l'information.
    """
    # Précalcul : sous-type d'article présent dans une row, peu importe la
    # priorité de sa source.
    article_subtype_present: str | None = None
    for r in rows:
        if not r["doc_type"]:
            continue
        mapped = map_doc_type(r["doc_type"], r["source"])
        if mapped in ARTICLE_SUBTYPES:
            article_subtype_present = mapped
            break

    for r in rows:
        if not r["doc_type"]:
            continue
        mapped = map_doc_type(r["doc_type"], r["source"])
        if mapped == "article" and article_subtype_present:
            return article_subtype_present
        return mapped
    return "other"


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """Résultat de `refresh_from_sources`.

    `absorbed_publication_id` non-None signale qu'une fusion a eu lieu pendant le refresh : une autre publication portait le DOI promu par l'agrégation cross-source, et a été absorbée dans la publication rafraîchie pour éviter une violation de la contrainte unique `publications_doi_lower_key`. L'id absorbé est mort en base ; le caller doit considérer toute référence externe à cette id comme dangling.
    """

    absorbed_publication_id: int | None = None


def refresh_from_sources(pub_id: int, *, repo: PublicationRepository) -> RefreshResult:
    """Recalcule les métadonnées d'une publication depuis ses source_publications.

    Contrairement à l'ancien _enrich() qui faisait du COALESCE incrémental (premier arrivé gagne, jamais de downgrade), cette fonction fait un recalcul complet : elle lit TOUS les source_publications attachés et réapplique les règles de priorité depuis zéro. Elle peut donc corriger des métadonnées obsolètes (ex: ongoing_thesis → thesis après soutenance).

    Règles de priorité entre sources :
    Ordre unique : theses.fr > ScanR > HAL > OpenAlex > WoS. Pour les documents hors thèse, la clé `theses` n'apparaît pas dans les rows, l'ordre se réduit donc à ScanR > HAL > OpenAlex > WoS.

    Règles de fusion par type de champ :
    • Scalaires (doi, doc_type, pub_year, journal_id, container_title, language) : premier non-null dans l'ordre de priorité.
    • Texte (abstract) : idem, premier non-null.
    • oa_status : le statut le plus ouvert parmi toutes les sources (diamond > gold > hybrid > bronze > green > closed > unknown).
    • Booléen (is_retracted) : True si au moins une source le dit.
    • Listes (keywords, countries) : union de toutes les sources, dédupliquée.
    • JSONB biblio, meta : fusion shallow par clé (clés généralement orthogonales entre sources) ; en cas de conflit sur une clé, la source prioritaire l'emporte.
    • JSONB topics : composite par source — {"openalex": [...], "theses": {...}, "scanr": ...}. Chaque source garde sa forme native (liste hiérarchique ou dict selon la source) pour ne rien perdre.

    Ne touche PAS à : title, title_normalized, notes, sources (utiliser update_sources() séparément).

    Auto-fusion sur conflit DOI :
    Si la promotion du DOI agrégé entre en collision avec une autre publication qui occupe déjà ce DOI, cette dernière est absorbée dans `pub_id` avant l'UPDATE — au lieu de laisser remonter une violation de contrainte unique. `pub_id` reste vivant pour le caller, et l'id absorbée est exposée dans `RefreshResult.absorbed_publication_id` pour que le caller puisse en tenir compte (logs, audit, nettoyage de références).
    """
    absorbed: int | None = None

    rows = repo.get_source_rows(pub_id)
    if not rows:
        return RefreshResult()

    rank = {s: i for i, s in enumerate(SOURCE_PRIORITY)}
    rows.sort(key=lambda r: rank.get(r["source"], 99))

    # Si le DOI à promouvoir est déjà occupé par une autre publication, fusionner d'abord pour éviter une violation de la contrainte unique `publications_doi_lower_key` au moment de l'UPDATE. Cas typique : une thèse avec un DOI ABES (10.70675/...) créée en double — une fois via OpenAlex (DOI seul, NNT inconnu) et une fois via theses.fr/HAL (NNT seul, DOI publié plus tard). Quand le DOI finit par apparaître dans une source_publication, sa promotion vers publications.doi collisionne avec la pub OpenAlex. La fusion absorbe l'autre dans `pub_id` (qui reste vivant pour le caller).
    new_doi = _first_non_null(rows, "doi")
    if new_doi:
        existing = repo.find_by_doi(new_doi)
        if existing and existing.id != pub_id:
            absorbed = existing.id
            merge_publications(pub_id, existing.id, repo=repo)
            rows = repo.get_source_rows(pub_id)
            rows.sort(key=lambda r: rank.get(r["source"], 99))

    repo.update_aggregated(
        pub_id,
        doi=_first_non_null(rows, "doi"),
        doc_type=_first_doc_type(rows),
        pub_year=_first_non_null(rows, "pub_year"),
        journal_id=_first_non_null(rows, "journal_id"),
        # Fallback à 'unknown' (DEFAULT côté schema) si toutes les sources sont silencieuses : best_oa_status renvoie None quand aucune valeur exploitable, et on ne veut pas écrire NULL sur la colonne canonique (le modèle Pydantic /api/publications attend un string non-null).
        oa_status=best_oa_status(r["oa_status"] for r in rows) or OA_STATUS_UNKNOWN_DEFAULT,
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
    return RefreshResult(absorbed_publication_id=absorbed)


def mark_distinct(
    pub_id_a: int,
    pub_id_b: int,
    *,
    repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Marque deux publications comme distinctes (non-doublon) dans
    `distinct_publications`. Idempotent.

    Les IDs sont triés pour garantir l'unicité de la paire.
    """
    inserted = repo.mark_distinct(pub_id_a, pub_id_b)
    if inserted:
        emit_event(
            audit_repo,
            "publication.marked_distinct",
            "publication",
            inserted[0],
            {"other_id": inserted[1]},
        )


def merge_publications(
    target_id: int,
    source_id: int,
    *,
    repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne la publication `source_id` dans `target_id`.

    Orchestration domain-driven :

    1. Charge `target` et `source` comme entités `Publication` via le repo.
    2. `target.absorb(source)` : enrichissement métadonnées en mémoire (règle pairwise OA, COALESCE des scalaires nullable, union countries) — vit dans l'aggregate.
    3. `repo.merge_into(target_id, source_id)` : plumbing FK (transfert des source_publications + authorships avec dédup, cleanup distinct_publications, DELETE de la ligne source).
    4. `repo.save(target)` : persistance des métadonnées enrichies. Fait APRÈS le DELETE pour éviter la collision sur la contrainte UNIQUE lower(doi) au cas où target a inhérité le DOI de source.
    5. Recalcule `sources` agrégé.
    6. Émet l'événement d'audit.

    Lève `NotFoundError` si target ou source n'existe pas.
    """
    target = repo.find_by_id(target_id)
    source = repo.find_by_id(source_id)
    if target is None:
        raise NotFoundError(f"Publication target #{target_id} introuvable")
    if source is None:
        raise NotFoundError(f"Publication source #{source_id} introuvable")

    target.absorb(source)
    repo.merge_into(target_id, source_id)
    repo.save(target)
    repo.update_sources(target_id)
    emit_event(
        audit_repo,
        "publication.merged",
        "publication",
        target_id,
        {"source_id": source_id},
    )
