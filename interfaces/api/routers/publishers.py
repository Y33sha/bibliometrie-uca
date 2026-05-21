"""Router Éditeurs — liste, recherche, fusion, types."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from application.ports.api.publishers_queries import (
    PublisherBasic,
    PublisherListResponse,
    PublisherQueries,
)
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository
from application.ports.repositories.publisher_repository import PublisherRepository
from application.publishers import merge_publishers
from application.publishers import update_publisher as _update_publisher
from domain.publishers.publisher import PUBLISHER_TYPES
from interfaces.api.deps import (
    audit_repo_sync,
    journal_repo_sync,
    publisher_queries_sync,
    publisher_repo_sync,
)
from interfaces.api.models import (
    EnumOption,
    MergeRequest,
    MergeResponse,
    OkResponse,
    PublisherUpdate,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# Mapping value enum → label FR (concern UI, donc côté router/interfaces, pas domain).
_PUBLISHER_TYPE_LABELS_FR: dict[str, str] = {
    "commercial": "Éditeur commercial",
    "learned_society": "Société savante",
    "academic_institution": "Établissement d'enseignement",
    "repository": "Archive / dépôt",
    "aggregator": "Agrégateur",
    "unknown": "Type inconnu",
}


@router.get("/api/publisher-types", response_model=list[EnumOption])
def list_publisher_types() -> list[EnumOption]:
    """Valeurs possibles de l'enum `publisher_type` avec leur label français.

    Source de vérité côté Python : `domain.publishers.publisher.PUBLISHER_TYPES`
    (test d'intégration `TestPublisherTypesEnum` vérifie la cohérence avec l'enum SQL).
    Sert à alimenter le dropdown de la page admin éditeurs.
    """
    return [EnumOption(value=v, label_fr=_PUBLISHER_TYPE_LABELS_FR[v]) for v in PUBLISHER_TYPES]


@router.get("/api/publishers", response_model=PublisherListResponse)
def list_publishers(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str | None = None,
    sort: str = "name",
    queries: PublisherQueries = Depends(publisher_queries_sync),
) -> PublisherListResponse:
    """Liste paginée des éditeurs avec comptage revues + publications.

    `search` : recherche sur le nom normalisé, ignorée si < 2
    caractères. `sort` : `name` / `-name` / `journals` / `-journals`
    / `pubs` / `-pubs` ; fallback sur `name` si inconnu.
    """
    return queries.list_publishers(search=search, sort=sort, page=page, per_page=per_page)


@router.get("/api/publishers/{publisher_id}", response_model=PublisherBasic)
def get_publisher(
    publisher_id: int,
    queries: PublisherQueries = Depends(publisher_queries_sync),
) -> PublisherBasic:
    """Récupère un éditeur par son id (nom uniquement). 404 si inconnu."""
    row = queries.get_publisher(publisher_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Éditeur introuvable")
    return row


@router.put("/api/publishers/{publisher_id}", response_model=OkResponse)
def update_publisher(
    publisher_id: int,
    body: PublisherUpdate,
    repo: PublisherRepository = Depends(publisher_repo_sync),
) -> OkResponse:
    """Met à jour un éditeur (modification sélective des champs fournis).

    Seuls les champs explicitement présents dans le body sont écrits
    (`exclude_unset=True`). Lève 404 si l'éditeur n'existe pas.
    """
    fields = body.model_dump(exclude_unset=True)
    _update_publisher(publisher_id, fields=fields, repo=repo)
    return OkResponse()


@router.post("/api/publishers/{publisher_id}/merge", response_model=MergeResponse)
def merge(
    publisher_id: int,
    body: MergeRequest,
    queries: PublisherQueries = Depends(publisher_queries_sync),
    pub_repo: PublisherRepository = Depends(publisher_repo_sync),
    j_repo: JournalRepository = Depends(journal_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> MergeResponse:
    """Fusionne l'éditeur `source_id` dans l'éditeur `publisher_id`.

    Les revues et publications rattachées à la source sont
    transférées à la cible ; la source est supprimée. 404 si l'un
    des deux éditeurs est introuvable.
    """
    found = queries.existing_publisher_ids((publisher_id, body.source_id))
    if publisher_id not in found:
        raise HTTPException(status_code=404, detail="Éditeur cible introuvable")
    if body.source_id not in found:
        raise HTTPException(status_code=404, detail="Éditeur source introuvable")

    merge_publishers(
        publisher_id,
        body.source_id,
        publisher_repo=pub_repo,
        journal_repo=j_repo,
        audit_repo=audit,
    )
    return MergeResponse(merged=True, source_id=body.source_id, target_id=publisher_id)
