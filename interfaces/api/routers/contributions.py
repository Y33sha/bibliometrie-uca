"""Router des contributions : exclusion d'une contribution, et revue des contributions orphelines. Sert `/api/contributions/*`.

Une contribution est un groupe de `contributions`. L'exclusion vise un groupe rattaché à une personne, par son `contribution_id`. Les orphelines sont les groupes du périmètre, sous un rôle d'auteur, rattachés à aucune personne, que le router liste et attribue sous `/orphans`, par leur `contribution_id`.

Les routes sont groupées par sujet, et les chemins littéraux précèdent celui qui porte un identifiant — un chemin littéral déclaré après `/{contribution_id}` s'y ferait absorber.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from application.ports.pipeline.publication_perimeter import PublicationPerimeterRecompute
from application.ports.read_models.contributions_queries import (
    ContributionsQueries,
    OrphanContributionsFacetsResponse,
    OrphanContributionsResponse,
    OrphanCountResponse,
    OrphanFilters,
)
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.contribution_repository import ContributionRepository
from application.ports.repositories.person_repository import PersonRepository
from application.services.contributions import commands as contribution_commands
from interfaces.api.deps import (
    audit_repo,
    contribution_repo,
    contributions_queries,
    db_conn,
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
    conn: Connection = Depends(db_conn),
    persons: PersonRepository = Depends(person_repo),
    contributions: ContributionRepository = Depends(contribution_repo),
    perimeter_recompute: PublicationPerimeterRecompute = Depends(publication_perimeter_recompute),
    audit: AuditRepository = Depends(audit_repo),
) -> OrphanAssignResponse:
    """Attribue une contribution orpheline à une personne, que la requête désigne ou fait créer.

    Renvoie 422 sans `person_id` ni `create_person`, et sans patronyme à la création (`assign_orphan_contribution`) ; 404 sur une personne ou un groupe introuvable ; 409 sur une paire déjà rejetée (`RejectedPairError`), à moins que `force` ne lève le rejet au passage, sur un groupe déjà rattaché à une personne (`ContributionAlreadyAssignedError`), et quand la personne a déjà un groupe manuel dans la publication (`PersonAlreadyInPublicationError`).
    """
    new_person: tuple[str, str] | None = None
    if body.create_person:
        new_person = (body.create_person.last_name, body.create_person.first_name)

    person_id = contribution_commands.assign_orphan_contribution(
        conn,
        body.contribution_id,
        person_id=body.person_id,
        new_person=new_person,
        repo=persons,
        contribution_repo=contributions,
        perimeter_recompute=perimeter_recompute,
        audit_repo=audit,
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
    conn: Connection = Depends(db_conn),
    persons: PersonRepository = Depends(person_repo),
    contributions: ContributionRepository = Depends(contribution_repo),
    perimeter_recompute: PublicationPerimeterRecompute = Depends(publication_perimeter_recompute),
    audit: AuditRepository = Depends(audit_repo),
) -> OrphanBatchAssignResponse:
    """Attribue plusieurs contributions orphelines à une personne existante.

    Les groupes absents ou déjà rattachés sont écartés du lot et journalisés ; le décompte rendu compte les groupes rattachés. Renvoie 404 sur une personne introuvable, 409 (`RejectedPairError`) dès qu'une paire du lot est déjà rejetée, à moins que `force` ne lève les rejets au passage.
    """
    if not body.group_ids:
        return OrphanBatchAssignResponse(assigned=0)

    assigned = contribution_commands.batch_assign_orphan_contributions(
        conn,
        body.person_id,
        body.group_ids,
        repo=persons,
        contribution_repo=contributions,
        perimeter_recompute=perimeter_recompute,
        audit_repo=audit,
        force=body.force,
    )
    return OrphanBatchAssignResponse(assigned=assigned)


# ── Exclusion de contributions ──────────────────────────────────────


@router.patch("/{contribution_id}/exclude", response_model=OkResponse)
def exclude_contribution(
    contribution_id: int,
    conn: Connection = Depends(db_conn),
    repo: ContributionRepository = Depends(contribution_repo),
    persons: PersonRepository = Depends(person_repo),
    perimeter_recompute: PublicationPerimeterRecompute = Depends(publication_perimeter_recompute),
    audit: AuditRepository = Depends(audit_repo),
) -> OkResponse:
    """Rejette une contribution : cette personne n'a pas signé cette publication.

    `contribution_id` désigne le groupe de la personne dans la publication. Enregistre la paire (publication, personne) dans `rejected_contributions`, puis détache le groupe et les contributions sources de la personne. La table de rejet vaut verrou : les reconstructions ultérieures respectent l'arbitrage. Le geste est à sens unique.
    """
    contribution_commands.exclude_contribution(
        conn,
        contribution_id,
        repo=repo,
        person_repo=persons,
        perimeter_recompute=perimeter_recompute,
        audit_repo=audit,
    )
    return OkResponse()
