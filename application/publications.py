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
from domain.publications.deduplication import (
    DeduplicationKey,
    decide_doi_attribution,
    decide_publication_match,
)
from domain.publications.deduplication import (
    resolve_doi_conflict as _domain_resolve_doi_conflict,
)
from domain.publications.identifiers import DOI
from domain.publications.merge import merge_source_rows
from domain.publications.metadata import (
    OA_STATUS_UNKNOWN_DEFAULT,
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

    Wrapper qui prefetch les données et délègue la décision à `decide_doi_attribution` (règle pure en domain). Trois sorties exclusives :

    - pas de DOI proposé OU la pub porte déjà un DOI → noop, retourne `pub_id` inchangé (politique conservative : on n'écrase pas un DOI existant).
    - DOI proposé déjà porté par une autre publication → fusion, retourne l'id de cette autre publication.
    - DOI libre → attribution à la pub courante, retourne `pub_id`.
    """
    current_doi = repo.get_doi(pub_id)
    existing_doi_match_id: int | None = None
    if not current_doi and doi:
        existing = repo.find_by_doi(doi)
        existing_doi_match_id = existing.id if existing else None

    decision = decide_doi_attribution(
        current_doi=current_doi,
        proposed_doi=doi,
        current_pub_id=pub_id,
        existing_doi_match_id=existing_doi_match_id,
    )

    if decision.action == "merge":
        assert decision.merge_with_id is not None  # garanti par la règle
        merge_publications(decision.merge_with_id, pub_id, repo=repo)
        return decision.merge_with_id
    if decision.action == "attribute":
        assert doi is not None  # garanti par la règle (proposed_doi truthy)
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

    # Prefetch DOI : résolution du conflit éventuel (chapter/book) qui peut invalider le DOI ou poser un id de fusion. La mutation `pub.doi = None` reflète le cas où la règle pure a rejeté le DOI.
    doi_merge_with_id: int | None = None
    if pub.doi is not None:
        existing_by_doi = repo.find_by_doi(str(pub.doi))
        if existing_by_doi:
            new_doi_str, doi_merge_with_id = resolve_doi_conflict(
                str(pub.doi),
                pub.doc_type or "",
                pub.title_normalized or "",
                existing_by_doi,
                repo=repo,
            )
            pub.doi = DOI(new_doi_str) if new_doi_str else None

    # Prefetch NNT (thèses uniquement).
    nnt_match_id: int | None = None
    if nnt:
        existing_by_nnt = repo.find_by_nnt(nnt)
        if existing_by_nnt:
            nnt_match_id = existing_by_nnt.id

    decision = decide_publication_match(
        doi_merge_with_id=doi_merge_with_id,
        nnt_match_id=nnt_match_id,
    )

    if decision.action == "match":
        assert decision.publication_id is not None
        # Enrichissement post-match : si la pub trouvée par NNT n'a pas encore le DOI proposé, on tente l'attribution tardive (ou fusion si le DOI est porté par une autre pub).
        if decision.matched_by == DeduplicationKey.NNT:
            try_merge_by_doi(
                decision.publication_id,
                str(pub.doi) if pub.doi else None,
                repo=repo,
            )
        return repo.find_by_id(decision.publication_id), False

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


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """Résultat de `refresh_from_sources`.

    `absorbed_publication_id` non-None signale qu'une fusion a eu lieu pendant le refresh : une autre publication portait le DOI promu par l'agrégation cross-source, et a été absorbée dans la publication rafraîchie pour éviter une violation de la contrainte unique `publications_doi_lower_key`. L'id absorbée est morte en base ; le caller doit considérer toute référence externe à cette id comme dangling.
    """

    absorbed_publication_id: int | None = None


def refresh_from_sources(pub_id: int, *, repo: PublicationRepository) -> RefreshResult:
    """Recalcule les métadonnées canoniques d'une publication depuis ses `source_publications`.

    Recalcul complet (pas de COALESCE incrémental qui figerait les valeurs au premier arrivé) : lit TOUS les `source_publications` attachés, applique l'algorithme de fusion `merge_source_rows` qui mute l'entité Publication en place, et persiste via `repo.save`. Peut corriger des métadonnées obsolètes (ex: `ongoing_thesis` → `thesis` après soutenance), et inclut désormais `title` / `title_normalized` dans l'agrégation cross-sources (ce qui n'était pas le cas auparavant).

    Auto-fusion sur conflit DOI : si la promotion du DOI agrégé entre en collision avec une autre publication qui occupe déjà ce DOI, cette dernière est absorbée dans `pub_id` avant le save — au lieu de laisser remonter une violation de la contrainte unique. `pub_id` reste vivant pour le caller, et l'id absorbée est exposée dans `RefreshResult.absorbed_publication_id`.

    Ne touche PAS à `notes` ni à `sources` (utiliser `update_sources` séparément).
    """
    rows = repo.get_source_rows(pub_id)
    if not rows:
        return RefreshResult()

    pub = repo.find_by_id(pub_id)
    if pub is None:
        return RefreshResult()

    # Si le DOI à promouvoir est déjà occupé par une autre publication, fusionner d'abord pour éviter une violation de la contrainte unique `publications_doi_lower_key`. Cas typique : une thèse avec un DOI ABES (10.70675/…) créée en double — une fois via OpenAlex (DOI seul, NNT inconnu) et une fois via theses.fr/HAL (NNT seul, DOI publié plus tard). Quand le DOI finit par apparaître dans une `source_publication`, sa promotion collisionne avec la pub OpenAlex. La fusion absorbe l'autre dans `pub_id` (qui reste vivant pour le caller).
    #
    # Le DOI brut est normalisé via le VO `DOI` avant le lookup : c'est cette forme normalisée (suffixe `.vN` strippé, lowercased) qui sera posée par `merge_source_rows`. Le pré-merge doit chercher la même forme, sinon des collisions échappent au mécanisme.
    absorbed: int | None = None
    rank = {s: i for i, s in enumerate(SOURCE_PRIORITY)}
    rows_sorted = sorted(rows, key=lambda r: rank.get(r["source"], 99))
    new_doi_raw = _first_non_null_doi(rows_sorted)
    new_doi_vo = DOI.try_parse(new_doi_raw) if new_doi_raw else None
    if new_doi_vo:
        existing = repo.find_by_doi(str(new_doi_vo))
        if existing and existing.id != pub_id:
            absorbed = existing.id
            merge_publications(pub_id, existing.id, repo=repo)
            rows = repo.get_source_rows(pub_id)
            # Recharger pub : ses attributs ont pu être enrichis via Publication.absorb pendant merge_publications.
            pub = repo.find_by_id(pub_id)
            if pub is None:
                return RefreshResult(absorbed_publication_id=absorbed)

    merge_source_rows(pub, rows, source_priority=SOURCE_PRIORITY)
    repo.save(pub)
    repo.update_sources(pub_id)
    return RefreshResult(absorbed_publication_id=absorbed)


def _first_non_null_doi(rows: list[dict[str, Any]]) -> str | None:
    """Premier `doi` non-null dans `rows` (déjà triées par priorité)."""
    for r in rows:
        if r["doi"]:
            return r["doi"]
    return None


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
