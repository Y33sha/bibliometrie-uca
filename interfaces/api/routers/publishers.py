"""Router des éditeurs : listes, recherche, édition, fusion. Sert `/api/publishers/*`."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection

from application.ports.api.publishers_queries import (
    Publisher,
    PublisherDashboardResponse,
    PublisherListResponse,
    PublisherQueries,
    PublishersFacetsResponse,
    PublisherSort,
)
from application.ports.api.subjects_queries import SubjectFrequency
from application.ports.pipeline.metadata_correction import MetadataCorrectionQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.ports.repositories.publisher_repository import (
    PublisherRepository,
    PublisherUpdate,
)
from application.services.publishers import commands as publisher_commands
from domain.publishers.publisher import PUBLISHER_TYPE_LABELS_FR, PUBLISHER_TYPES
from interfaces.api.deps import (
    audit_repo,
    db_conn,
    journal_repo,
    metadata_correction_queries,
    publication_repo,
    publisher_queries,
    publisher_repo,
)
from interfaces.api.filters import parse_str_csv
from interfaces.api.models import (
    EnumOption,
    MergeRequest,
    MergeResponse,
    OkResponse,
    PublisherMergeBlockedResponse,
)
from interfaces.api.params import TOP_SUBJECTS_LIMIT, TopSubjectsLimit

router = APIRouter(prefix="/api/publishers", tags=["publishers"])


@router.get("/types", response_model=list[EnumOption])
def list_publisher_types() -> list[EnumOption]:
    """Valeurs possibles de l'enum `publisher_type` avec leur libellé français.

    La source de vérité côté Python est `domain.publishers.publisher.PUBLISHER_TYPES` et `PUBLISHER_TYPE_LABELS_FR`, dont un test d'intégration vérifie l'accord avec l'enum SQL. Alimente la liste déroulante de la page admin des éditeurs et la colonne « Type » des pages publiques.
    """
    return [EnumOption(value=v, label_fr=PUBLISHER_TYPE_LABELS_FR[v]) for v in PUBLISHER_TYPES]


@router.get("/facets", response_model=PublishersFacetsResponse)
def publishers_facets(
    search: str | None = None,
    publisher_type: str = Query(""),
    country: str = Query(""),
    with_pubs: bool = False,
    queries: PublisherQueries = Depends(publisher_queries),
) -> PublishersFacetsResponse:
    """Comptes par option des facettes de la liste des éditeurs.

    Convention partagée avec `/api/journals/facets` et `/api/publications/facets` : chaque facette écarte sa propre dimension de la clause WHERE.
    """
    return queries.publishers_facets(
        search=search,
        publisher_types=parse_str_csv(publisher_type),
        countries=parse_str_csv(country),
        with_pubs=with_pubs,
    )


@router.get("", response_model=PublisherListResponse)
def list_publishers(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str | None = None,
    publisher_type: str = Query(""),
    country: str = Query(""),
    with_pubs: bool = False,
    sort: PublisherSort = "name_asc",
    queries: PublisherQueries = Depends(publisher_queries),
) -> PublisherListResponse:
    """Liste paginée des éditeurs, avec le décompte de leurs revues et de leurs publications.

    Filtres :

    - `search` : insensible à la casse sur le nom normalisé, ignoré en deçà de deux caractères.
    - `publisher_type` et `country` : valeurs séparées par des virgules (par exemple `commercial,learned_society`), vide valant absence de filtre, selon la convention multi-valeurs de `/api/journals` et `/api/publications`.
    - `with_pubs` : restreint aux éditeurs dont le `pub_count` est non nul. Ce compteur ne retient que les publications du périmètre, atteintes par les revues de l'éditeur : un éditeur dont toutes les publications sont hors périmètre est donc « orphelin ». La page publique s'en sert pour les masquer, que l'admin garde la possibilité de voir.

    `sort` accepte `name`, `journals` et `pubs`, suffixés de `_asc` ou `_desc` ; toute autre valeur rend un 422.
    """
    return queries.list_publishers(
        search=search,
        publisher_types=parse_str_csv(publisher_type),
        countries=parse_str_csv(country),
        with_pubs=with_pubs,
        sort=sort,
        page=page,
        per_page=per_page,
    )


@router.get("/{publisher_id}", response_model=Publisher)
def get_publisher(
    publisher_id: int,
    queries: PublisherQueries = Depends(publisher_queries),
) -> Publisher:
    """Profil complet d'un éditeur, pour sa page publique.

    Porte ses métadonnées, ses préfixes DOI, et le décompte de ses revues et de ses publications. Renvoie 404 sur un éditeur inconnu.
    """
    row = queries.get_publisher_detail(publisher_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Éditeur introuvable")
    return row


@router.get("/{publisher_id}/dashboard", response_model=PublisherDashboardResponse)
def get_publisher_dashboard(
    publisher_id: int,
    queries: PublisherQueries = Depends(publisher_queries),
) -> PublisherDashboardResponse:
    """Agrégats de l'onglet tableau de bord de la page d'un éditeur.

    Distribution des `journal_type` de son catalogue, et distributions des `doc_type` et `oa_status` des publications que ses revues portent. Renvoie 404 sur un éditeur inconnu.
    """
    result = queries.get_publisher_dashboard(publisher_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Éditeur introuvable")
    return result


@router.get("/{publisher_id}/subjects", response_model=list[SubjectFrequency])
def get_publisher_subjects(
    publisher_id: int,
    limit: TopSubjectsLimit = TOP_SUBJECTS_LIMIT,
    queries: PublisherQueries = Depends(publisher_queries),
) -> list[SubjectFrequency]:
    """Sujets les plus fréquents des publications de l'éditeur, pour l'onglet tableau de bord.

    Les sujets trop génériques sont écartés. Un éditeur sans publication indexée donne une liste vide.
    """
    return queries.get_publisher_subjects(publisher_id, limit=limit)


@router.put("/{publisher_id}", response_model=OkResponse)
def update_publisher(
    publisher_id: int,
    body: PublisherUpdate,
    conn: Connection = Depends(db_conn),
    repo: PublisherRepository = Depends(publisher_repo),
) -> OkResponse:
    """Met à jour un éditeur, champ par champ.

    Seuls les champs présents dans le corps de la requête sont écrits (`exclude_unset=True`). Renvoie 404 sur un éditeur inconnu.
    """
    publisher_commands.update_publisher(conn, publisher_id, update=body, repo=repo)
    return OkResponse()


@router.post(
    "/{publisher_id}/merge",
    response_model=MergeResponse,
    responses={409: {"model": PublisherMergeBlockedResponse}},
)
def merge(
    publisher_id: int,
    body: MergeRequest,
    conn: Connection = Depends(db_conn),
    publisher_repo: PublisherRepository = Depends(publisher_repo),
    journal_repo: JournalRepository = Depends(journal_repo),
    publication_repo: PublicationRepository = Depends(publication_repo),
    audit_repo: AuditRepository = Depends(audit_repo),
    correction_queries: MetadataCorrectionQueries = Depends(metadata_correction_queries),
) -> MergeResponse:
    """Fusionne l'éditeur `source_id` dans l'éditeur `publisher_id`.

    Les revues et les publications de la source passent à la cible, puis la source est supprimée. Deux revues au titre partagé entre les deux éditeurs sont fondues en une, et leurs publications requalifiées contre le `journal_type` de la cible (`merge_journals`).

    Cette fusion de revues peut buter : ISSN divergents pour un même titre, ou doublon interne de titre chez l'un des éditeurs. La fusion entière est alors refusée par un 409 (`PublisherMergeBlockedResponse`), dont le corps énumère toutes les paires bloquantes ; l'admin les traite côté revues avant de relancer. Renvoie aussi 400 sur deux identifiants égaux, 404 si l'un des deux éditeurs est introuvable.
    """
    publisher_commands.merge_publishers(
        conn,
        publisher_id,
        body.source_id,
        correction_queries=correction_queries,
        publisher_repo=publisher_repo,
        journal_repo=journal_repo,
        publication_repo=publication_repo,
        audit_repo=audit_repo,
    )
    return MergeResponse(merged=True, source_id=body.source_id, target_id=publisher_id)
