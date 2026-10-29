"""Router des contributions : exclusion d'une contribution, et revue des contributions orphelines. Sert `/api/contributions/*`.

L'exclusion vise une contribution rattachée à une personne, par son `contribution_id`. Les orphelines sont les contributions du périmètre, sous un rôle d'auteur, rattachées à aucune personne, que le router liste et attribue sous `/orphans`, par leur `contribution_id`.

Les routes sont groupées par sujet, et les chemins littéraux précèdent celui à identifiant : déclaré après `/{contribution_id}`, un chemin littéral s'y ferait absorber.
"""

from typing import cast

from fastapi import APIRouter, Depends, Query

from application.services.contributions import ContributionService
from infrastructure.read_models.contributions.models import (
    OrphanContributionsFacetsResponse,
    OrphanContributionsResponse,
    OrphanCountResponse,
    OrphanFilters,
)
from infrastructure.read_models.contributions.queries import ContributionsQueries
from interfaces.api.deps import contribution_service, contributions_queries
from interfaces.api.filters import parse_lab_id
from interfaces.api.models import (
    AssignOrphanContribution,
    BatchAssignOrphanContributions,
    OkResponse,
    OrphanAssignResponse,
    OrphanBatchAssignResponse,
    RejectedPairsResponse,
)
from interfaces.api.params import SearchTerm

router = APIRouter(prefix="/api/contributions", tags=["contributions"])


# ── Contributions orphelines ───────────────────────────────────────


@router.get("/orphans/count", response_model=OrphanCountResponse)
def orphan_contributions_count(
    queries: ContributionsQueries = Depends(contributions_queries),
) -> OrphanCountResponse:
    """Nombre de contributions orphelines."""
    return queries.orphan_contributions_count()


def orphan_filters(search: SearchTerm = "", lab_id: str = Query("")) -> OrphanFilters:
    """Filtres communs à la liste des contributions orphelines et à sa facette. `lab_id` prend des identifiants de laboratoires et `none` pour les contributions sans laboratoire."""
    lab_ids, lab_none = parse_lab_id(lab_id)
    return OrphanFilters(search=search, lab_ids=lab_ids, lab_none=lab_none)


@router.get("/orphans", response_model=OrphanContributionsResponse)
def list_orphan_contributions(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    filters: OrphanFilters = Depends(orphan_filters),
    queries: ContributionsQueries = Depends(contributions_queries),
) -> OrphanContributionsResponse:
    """Liste les contributions orphelines."""
    return queries.list_orphan_contributions(filters=filters, page=page, per_page=per_page)


@router.get("/orphans/facets", response_model=OrphanContributionsFacetsResponse)
def orphan_contributions_facets(
    filters: OrphanFilters = Depends(orphan_filters),
    queries: ContributionsQueries = Depends(contributions_queries),
) -> OrphanContributionsFacetsResponse:
    """Facette laboratoires des contributions orphelines."""
    return queries.orphan_contributions_facets(filters=filters)


@router.post(
    "/orphans/assign",
    response_model=OrphanAssignResponse,
    responses={409: {"model": RejectedPairsResponse}},
)
def assign_orphan_contribution(
    body: AssignOrphanContribution,
    contributions: ContributionService = Depends(contribution_service),
) -> OrphanAssignResponse:
    """Attribue une contribution orpheline à une personne, que la requête désigne ou fait créer.

    Renvoie 422 sans `person_id` ni `create_person`, et sans nom de famille à la création (`assign_orphan_contribution_to_new_person`) ; 404 sur une personne ou une contribution introuvable ; 409 sur une paire déjà rejetée (`RejectedPairError`), sauf si `force` retire le rejet au passage, sur une contribution déjà rattachée à une personne (`ContributionAlreadyAssignedError`), et quand la personne a déjà une contribution manuelle dans la publication (`PersonAlreadyInPublicationError`).
    """
    if body.create_person is not None:
        person_id = contributions.assign_orphan_contribution_to_new_person(
            body.contribution_id,
            body.create_person.last_name,
            body.create_person.first_name,
            force=body.force,
        )
    else:
        person_id = cast(int, body.person_id)
        contributions.assign_orphan_contribution(person_id, body.contribution_id, force=body.force)
    return OrphanAssignResponse(person_id=person_id)


@router.post(
    "/orphans/batch-assign",
    response_model=OrphanBatchAssignResponse,
    responses={409: {"model": RejectedPairsResponse}},
)
def batch_assign_orphan_contributions(
    body: BatchAssignOrphanContributions,
    contributions: ContributionService = Depends(contribution_service),
) -> OrphanBatchAssignResponse:
    """Attribue plusieurs contributions orphelines à une personne existante.

    Les contributions absentes ou déjà rattachées sont écartées du lot et journalisées ; le décompte rendu compte les contributions rattachées. Renvoie 404 sur une personne introuvable, 409 (`RejectedPairError`) dès qu'une paire du lot est déjà rejetée, sauf si `force` retire les rejets au passage.
    """
    if not body.contribution_ids:
        return OrphanBatchAssignResponse(assigned=0)

    assigned = contributions.batch_assign_orphan_contributions(
        body.person_id, body.contribution_ids, force=body.force
    )
    return OrphanBatchAssignResponse(assigned=assigned)


# ── Exclusion de contributions ──────────────────────────────────────


@router.patch("/{contribution_id}/exclude", response_model=OkResponse)
def exclude_contribution(
    contribution_id: int,
    contributions: ContributionService = Depends(contribution_service),
) -> OkResponse:
    """Rejette une contribution : la personne n'a pas signé la publication.

    Enregistre la paire (publication, personne) dans `rejected_contributions`, puis détache la contribution et les contributions sources de la personne. Le rejet survit aux runs suivants ; seule une attribution forcée d'une contribution orpheline le retire.
    """
    contributions.exclude_contribution(contribution_id)
    return OkResponse()
