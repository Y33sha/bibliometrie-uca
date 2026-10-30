"""Router des éditeurs : listes, recherche, édition, fusion. Sert `/api/publishers/*`.

Les chemins littéraux (`/types`, `/facets`, `/export.csv`) précèdent `/{publisher_id}`, qui les accepterait sinon comme identifiant.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from application.ports.repositories.publisher_repository import PublisherUpdate
from application.services.publishers import PublisherService
from domain.merge import MergedEntity
from domain.publishers.publisher import PUBLISHER_TYPE_LABELS_FR, PUBLISHER_TYPES
from infrastructure.read_models.publishers.models import (
    Publisher,
    PublisherFilters,
    PublisherListResponse,
    PublishersFacetsResponse,
    PublisherSort,
)
from infrastructure.read_models.publishers.queries import PublisherQueries
from infrastructure.read_models.subjects.models import SubjectFrequency
from interfaces.api.csv_export import csv_response
from interfaces.api.deps import entity_detail, publisher_queries, publisher_service
from interfaces.api.entity_detail import EntityDetail
from interfaces.api.filters import parse_str_csv, parse_vocabulary_csv
from interfaces.api.models import (
    EnumOption,
    MergeRequest,
    MergeResponse,
    OkResponse,
    PublisherMergeBlockedResponse,
)
from interfaces.api.params import TOP_SUBJECTS_LIMIT, SearchTerm, TopSubjectsLimit
from interfaces.api.rate_limit import ExportSlot, export_rate_limit, export_slot

router = APIRouter(prefix="/api/publishers", tags=["publishers"])


@router.get("/types", response_model=list[EnumOption])
def list_publisher_types() -> list[EnumOption]:
    """Liste les valeurs possibles de l'enum `publisher_type` avec leur libellé français.

    Les valeurs viennent de `domain.publishers.publisher.PUBLISHER_TYPES` et `PUBLISHER_TYPE_LABELS_FR`. Un test d'intégration vérifie leur accord avec l'enum SQL. Alimente la liste déroulante de la page d'administration des éditeurs et la colonne « Type » des pages publiques.
    """
    return [EnumOption(value=v, label_fr=PUBLISHER_TYPE_LABELS_FR[v]) for v in PUBLISHER_TYPES]


def publisher_filters(
    search: SearchTerm = "",
    publisher_type: str = Query(""),
    country: str = Query(""),
    has_publications: bool | None = Query(None),
) -> PublisherFilters:
    """Lit les filtres communs à la liste des éditeurs et à ses facettes.

    `publisher_type` accepte plusieurs valeurs séparées par des virgules, prises dans l'énumération du domaine ; une valeur inconnue renvoie 422. `country` suit la même convention multi-valeurs, sur les codes du référentiel. `search` agit à partir de deux caractères.
    """
    return PublisherFilters(
        search=search,
        publisher_types=parse_vocabulary_csv(
            publisher_type, allowed=PUBLISHER_TYPES, param="publisher_type"
        ),
        countries=parse_str_csv(country),
        has_publications=has_publications,
    )


@router.get("/facets", response_model=PublishersFacetsResponse)
def publishers_facets(
    filters: PublisherFilters = Depends(publisher_filters),
    queries: PublisherQueries = Depends(publisher_queries),
) -> PublishersFacetsResponse:
    """Renvoie les décomptes par option des facettes de la liste des éditeurs.

    Convention partagée avec `/api/serials/facets` et `/api/publications/facets` : chaque facette écarte sa propre dimension de la clause WHERE.
    """
    return queries.publishers_facets(filters=filters)


@router.get("/export.csv")
def export_publishers_csv(
    sort: PublisherSort = "name_asc",
    filters: PublisherFilters = Depends(publisher_filters),
    queries: PublisherQueries = Depends(publisher_queries),
    _rate_limit: None = Depends(export_rate_limit),
    slot: ExportSlot = Depends(export_slot),
) -> StreamingResponse:
    """Exporte en CSV la liste des éditeurs, aux filtres et au tri de la liste."""
    return csv_response(
        queries.export_publishers_csv(filters=filters, sort=sort),
        filename="editeurs.csv",
        slot=slot,
    )


@router.get("", response_model=PublisherListResponse)
def list_publishers(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort: PublisherSort = "name_asc",
    filters: PublisherFilters = Depends(publisher_filters),
    queries: PublisherQueries = Depends(publisher_queries),
) -> PublisherListResponse:
    """Liste les éditeurs par page, avec le décompte de leurs revues et de leurs publications.

    `has_publications` retient les éditeurs à décompte de publications non nul (`true`) ou nul (`false`). Ce décompte retient seulement les publications du périmètre, atteintes par les revues de l'éditeur. `sort` accepte `name`, `serials` et `publications`, suffixés de `_asc` ou `_desc` ; toute autre valeur renvoie un 422.
    """
    return queries.list_publishers(filters=filters, sort=sort, page=page, per_page=per_page)


@router.get("/{publisher_id}", response_model=Publisher)
def get_publisher(
    publisher_id: int,
    queries: PublisherQueries = Depends(publisher_queries),
    detail: EntityDetail = Depends(entity_detail(MergedEntity.PUBLISHER)),
) -> Publisher:
    """Renvoie le profil complet d'un éditeur, pour sa page publique.

    Le profil contient ses métadonnées, ses préfixes DOI, et le décompte de ses revues et de ses publications.
    """
    return detail.found(queries.get_publisher_detail(publisher_id))


@router.get("/{publisher_id}/subjects", response_model=list[SubjectFrequency])
def get_publisher_subjects(
    publisher_id: int,
    limit: TopSubjectsLimit = TOP_SUBJECTS_LIMIT,
    queries: PublisherQueries = Depends(publisher_queries),
) -> list[SubjectFrequency]:
    """Renvoie les sujets les plus fréquents des publications de l'éditeur, pour l'onglet tableau de bord.

    Les sujets trop génériques sont écartés. Un éditeur sans publication indexée donne une liste vide.
    """
    return queries.get_publisher_subjects(publisher_id, limit=limit)


@router.put("/{publisher_id}", response_model=OkResponse)
def update_publisher(
    publisher_id: int,
    body: PublisherUpdate,
    publishers: PublisherService = Depends(publisher_service),
) -> OkResponse:
    """Met à jour un éditeur, champ par champ.

    Seuls les champs présents dans le corps de la requête sont écrits. Renvoie 404 sur un éditeur inconnu.
    """
    publishers.update_publisher(publisher_id, body)
    return OkResponse()


@router.post(
    "/{publisher_id}/merge",
    response_model=MergeResponse,
    responses={409: {"model": PublisherMergeBlockedResponse}},
)
def merge(
    publisher_id: int,
    body: MergeRequest,
    publishers: PublisherService = Depends(publisher_service),
) -> MergeResponse:
    """Fusionne l'éditeur `source_id` dans l'éditeur `publisher_id`.

    Les revues et les publications de la source passent à la cible, puis la source est supprimée. Deux revues au titre partagé entre les deux éditeurs sont fondues en une, et leurs publications requalifiées contre le `serial_type` de la cible (`merge_serials`).

    Deux éditeurs aux membres Crossref distincts sont deux maisons : la fusion est refusée par un 409.

    La fusion des revues bloque sur des ISSN divergents pour un même titre, ou sur un doublon de titre chez l'un des éditeurs. La fusion entière est alors refusée par un 409 (`PublisherMergeBlockedResponse`). Son corps énumère toutes les paires bloquantes, à traiter dans les revues avant de relancer. Renvoie aussi 422 sur deux identifiants égaux, 404 si l'un des deux éditeurs est introuvable.
    """
    publishers.merge_publishers(publisher_id, body.source_id)
    return MergeResponse(merged=True, source_id=body.source_id, target_id=publisher_id)
