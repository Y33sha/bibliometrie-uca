"""Router des monographies : liste, fiche et édition. Sert `/api/monographs/*`."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection

from application.ports.read_models.monographs_queries import (
    MonographFilters,
    MonographKind,
    MonographListItem,
    MonographListResponse,
    MonographQueries,
    MonographSort,
)
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.monograph_repository import (
    MonographRepository,
    MonographUpdate,
)
from application.services.monographs import commands as monograph_commands
from interfaces.api.deps import audit_repo, db_conn, monograph_queries, monograph_repo
from interfaces.api.models import OkResponse
from interfaces.api.params import SearchTerm

router = APIRouter(prefix="/api/monographs", tags=["monographs"])


@router.get("", response_model=MonographListResponse)
def list_monographs(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort: MonographSort = "pubs_desc",
    search: SearchTerm = "",
    kind: MonographKind = "",
    queries: MonographQueries = Depends(monograph_queries),
) -> MonographListResponse:
    """Liste paginée des monographies, avec leur éditeur, leur collection et le nombre de publications qu'elles contiennent.

    `search` porte sur le titre, ou sur l'ISBN quand le terme commence par 978 ou 979. `kind` restreint aux livres (`book`) ou aux volumes d'actes (`proceedings`).
    """
    return queries.list_monographs(
        filters=MonographFilters(search=search, kind=kind), sort=sort, page=page, per_page=per_page
    )


@router.get("/{monograph_id}", response_model=MonographListItem)
def get_monograph(
    monograph_id: int,
    queries: MonographQueries = Depends(monograph_queries),
) -> MonographListItem:
    """Fiche d'une monographie. Renvoie 404 sur une monographie inconnue."""
    row = queries.get_monograph(monograph_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Monographie introuvable")
    return row


@router.put("/{monograph_id}", response_model=OkResponse)
def update_monograph(
    monograph_id: int,
    body: MonographUpdate,
    conn: Connection = Depends(db_conn),
    repo: MonographRepository = Depends(monograph_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> OkResponse:
    """Met à jour une monographie, champ par champ. Renvoie 404 sur une monographie inconnue."""
    monograph_commands.update_monograph(
        conn, monograph_id, update=body, repo=repo, audit_repo=audit
    )
    return OkResponse()
