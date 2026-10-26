"""Router des contributions : exclusion d'une contribution, et revue des contributions orphelines. Sert `/api/contributions/*`.

L'exclusion vise une contribution rattachée à une personne, par son `contribution_id`. Les orphelines sont les contributions du périmètre, sous un rôle d'auteur, rattachées à aucune personne, que le router liste et attribue sous `/orphans`, par leur `contribution_id`.

Les routes sont groupées par sujet, et les chemins littéraux précèdent celui qui porte un identifiant — un chemin littéral déclaré après `/{contribution_id}` s'y ferait absorber.
"""

from typing import cast

from fastapi import APIRouter, Depends, Query

from application.ports.pipeline.publication_perimeter import PublicationPerimeterRecompute
from application.ports.read_models.contributions_queries import (
    ContributionsQueries,
    OrphanContributionsFacetsResponse,
    OrphanContributionsResponse,
    OrphanCountResponse,
    OrphanFilters,
)
from application.ports.repositories.contribution_repository import ContributionRepository
from application.ports.repositories.person_repository import PersonRepository
from application.services.contributions import assign_orphans, core as contributions_service
from interfaces.api.deps import (
    contribution_repo,
    contributions_queries,
    person_repo,
    publication_perimeter_recompute,
)
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
    persons: PersonRepository = Depends(person_repo),
    contributions: ContributionRepository = Depends(contribution_repo),
    perimeter_recompute: PublicationPerimeterRecompute = Depends(publication_perimeter_recompute),
) -> OrphanAssignResponse:
    """Attribue une contribution orpheline à une personne, que la requête désigne ou fait créer.

    Renvoie 422 sans `person_id` ni `create_person`, et sans patronyme à la création (`assign_orphan_contribution_to_new_person`) ; 404 sur une personne ou un groupe introuvable ; 409 sur une paire déjà rejetée (`RejectedPairError`), à moins que `force` ne lève le rejet au passage, sur un groupe déjà rattaché à une personne (`ContributionAlreadyAssignedError`), et quand la personne a déjà un groupe manuel dans la publication (`PersonAlreadyInPublicationError`).
    """
    if body.create_person is not None:
        person_id = assign_orphans.assign_orphan_contribution_to_new_person(
            body.contribution_id,
            body.create_person.last_name,
            body.create_person.first_name,
            repo=persons,
            contribution_repo=contributions,
            perimeter_recompute=perimeter_recompute,
            force=body.force,
        )
    else:
        person_id = cast(int, body.person_id)
        assign_orphans.assign_orphan_contribution(
            person_id,
            body.contribution_id,
            repo=persons,
            contribution_repo=contributions,
            perimeter_recompute=perimeter_recompute,
            force=body.force,
        )
    return OrphanAssignResponse(person_id=person_id)


@router.post(
    "/orphans/batch-assign",
    response_model=OrphanBatchAssignResponse,
    responses={409: {"model": RejectedPairsResponse}},
)
def batch_assign_orphan_contributions(
    body: BatchAssignOrphanContributions,
    persons: PersonRepository = Depends(person_repo),
    contributions: ContributionRepository = Depends(contribution_repo),
    perimeter_recompute: PublicationPerimeterRecompute = Depends(publication_perimeter_recompute),
) -> OrphanBatchAssignResponse:
    """Attribue plusieurs contributions orphelines à une personne existante.

    Les groupes absents ou déjà rattachés sont écartés du lot et journalisés ; le décompte rendu compte les groupes rattachés. Renvoie 404 sur une personne introuvable, 409 (`RejectedPairError`) dès qu'une paire du lot est déjà rejetée, à moins que `force` ne lève les rejets au passage.
    """
    if not body.group_ids:
        return OrphanBatchAssignResponse(assigned=0)

    assigned = assign_orphans.batch_assign_orphan_contributions(
        body.person_id,
        body.group_ids,
        repo=persons,
        contribution_repo=contributions,
        perimeter_recompute=perimeter_recompute,
        force=body.force,
    )
    return OrphanBatchAssignResponse(assigned=assigned)


# ── Exclusion de contributions ──────────────────────────────────────


@router.patch("/{contribution_id}/exclude", response_model=OkResponse)
def exclude_contribution(
    contribution_id: int,
    repo: ContributionRepository = Depends(contribution_repo),
    persons: PersonRepository = Depends(person_repo),
    perimeter_recompute: PublicationPerimeterRecompute = Depends(publication_perimeter_recompute),
) -> OkResponse:
    """Rejette une contribution : cette personne n'a pas signé cette publication.

    `contribution_id` désigne le groupe de la personne dans la publication. Enregistre la paire (publication, personne) dans `rejected_contributions`, puis détache le groupe et les contributions sources de la personne. La table de rejet vaut verrou : les reconstructions ultérieures respectent l'arbitrage. Le geste est à sens unique.
    """
    contributions_service.exclude_contribution(
        contribution_id,
        repo=repo,
        person_repo=persons,
        perimeter_recompute=perimeter_recompute,
    )
    return OkResponse()
