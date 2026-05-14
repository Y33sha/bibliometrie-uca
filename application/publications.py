"""
Service Publications — accès exclusif en écriture à la table `publications`.

Toute création, mise à jour ou recherche de publication passe par ce module.
Les scripts de normalisation (HAL, OpenAlex, WoS, ScanR) et les autres
traitements appellent ces fonctions au lieu de faire du SQL direct.

Les fonctions find_by_* retournent des namedtuples pour un accès par nom
indépendant du type de curseur (tuple ou dict_row).
"""

from dataclasses import dataclass

from application.audit import emit_event
from domain.errors import NotFoundError
from domain.ports.audit_repository import AuditRepository
from domain.ports.publication_repository import PublicationRepository
from domain.publication import (
    PubByDoi,
    PubByNnt,
    PubByTitle,
    PubThesisCandidate,
)
from domain.publications.deduplication import (
    resolve_doi_conflict as _domain_resolve_doi_conflict,
)
from domain.publications.identifiers import DOI
from domain.publications.merge import first_non_null, merge_source_rows
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


def update_oa_status(pub_id: int, oa_status: str, *, repo: PublicationRepository) -> None:
    """Met à jour le statut OA d'une publication."""
    repo.update_oa_status(pub_id, oa_status)


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


def refresh_from_sources(
    pub_id: int,
    *,
    repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> RefreshResult:
    """Recalcule les métadonnées canoniques d'une publication depuis ses `source_publications`.

    Recalcul complet (pas de COALESCE incrémental qui figerait les valeurs au premier arrivé) : lit TOUS les `source_publications` attachés, applique l'algorithme d'agrégation `merge_source_rows` (domain) qui mute l'entité Publication en place, et persiste via `repo.save`. Peut corriger des métadonnées obsolètes (ex: `ongoing_thesis` → `thesis` après soutenance).

    **Cas orphelin** : si la publication n'a aucune source rattachée, la règle métier dicte qu'elle ne doit pas exister. `merge_source_rows` retourne `RefreshOutcome(is_orphan=True)` ; le caller (cette fonction) supprime la publication via `repo.delete` et émet un événement `publication.deleted_orphan`.

    Auto-fusion sur conflit DOI : si la promotion du DOI agrégé entre en collision avec une autre publication qui occupe déjà ce DOI, cette dernière est absorbée dans `pub_id` avant le save — au lieu de laisser remonter une violation de la contrainte unique. `pub_id` reste vivant pour le caller, et l'id absorbée est exposée dans `RefreshResult.absorbed_publication_id`.

    Si `audit_repo` est fourni et que le DOI canonique change effectivement (passage d'une valeur à une autre, ou perte du DOI), un événement `publication.doi_changed` est émis avec l'ancienne et la nouvelle valeur. Pas d'event sur l'attribution initiale (passage de None à une valeur) ni quand la valeur reste identique.

    Ne touche PAS à `notes` ni à `sources` (utiliser `update_sources` séparément).
    """
    pub = repo.find_by_id(pub_id)
    if pub is None:
        return RefreshResult()

    rows = repo.get_source_rows(pub_id)
    if not rows:
        # Pub orpheline : suppression côté caller (la règle métier est signalée par merge_source_rows quand on l'appellera ; ici on court-circuite parce qu'on n'a pas besoin d'agréger pour décider).
        repo.delete(pub_id)
        emit_event(audit_repo, "publication.deleted_orphan", "publication", pub_id, {})
        return RefreshResult()

    # Si le DOI à promouvoir est déjà occupé par une autre publication, fusionner d'abord pour éviter une violation de la contrainte unique `publications_doi_lower_key`. Cas typique : une thèse avec un DOI ABES (10.70675/…) créée en double — une fois via OpenAlex (DOI seul, NNT inconnu) et une fois via theses.fr/HAL (NNT seul, DOI publié plus tard). Quand le DOI finit par apparaître dans une `source_publication`, sa promotion collisionne avec la pub OpenAlex. La fusion absorbe l'autre dans `pub_id` (qui reste vivant pour le caller).
    #
    # Le DOI brut est normalisé via le VO `DOI` avant le lookup : c'est cette forme normalisée (suffixe `.vN` strippé, lowercased) qui sera posée par `merge_source_rows`. Le pré-merge doit chercher la même forme, sinon des collisions échappent au mécanisme.
    absorbed: int | None = None
    rank = {s: i for i, s in enumerate(SOURCE_PRIORITY)}
    rows_sorted = sorted(rows, key=lambda r: rank.get(r["source"], 99))
    new_doi_raw = first_non_null(rows_sorted, "doi")
    new_doi_vo = DOI.try_parse(new_doi_raw) if new_doi_raw else None
    if new_doi_vo:
        existing = repo.find_by_doi(str(new_doi_vo))
        if existing and existing.id != pub_id:
            absorbed = existing.id
            merge_publications(pub_id, existing.id, repo=repo, audit_repo=audit_repo)
            rows = repo.get_source_rows(pub_id)
            # Recharger pub : ses attributs ont pu être enrichis via Publication.absorb pendant merge_publications.
            pub = repo.find_by_id(pub_id)
            if pub is None:
                return RefreshResult(absorbed_publication_id=absorbed)

    previous_doi = pub.doi
    merge_source_rows(pub, rows, source_priority=SOURCE_PRIORITY)
    repo.save(pub)
    repo.update_sources(pub_id)

    if previous_doi is not None and pub.doi != previous_doi:
        emit_event(
            audit_repo,
            "publication.doi_changed",
            "publication",
            pub_id,
            {
                "previous_doi": str(previous_doi),
                "new_doi": str(pub.doi) if pub.doi else None,
            },
        )

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
