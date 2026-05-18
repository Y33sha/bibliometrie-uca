"""Router Revues — liste, recherche, fusion."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from application.journals import merge_journals
from application.journals import update_journal as _update_journal
from application.ports.api.journals_queries import (
    JournalBasic,
    JournalListResponse,
    JournalQueries,
)
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository
from interfaces.api.deps import (
    audit_repo_sync,
    journal_queries_sync,
    journal_repo_sync,
)
from interfaces.api.models import JournalUpdate, MergeRequest, MergeResponse, OkResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/journals", response_model=JournalListResponse)
def list_journals(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str | None = None,
    publisher_id: int | None = None,
    sort: str = "title",
    queries: JournalQueries = Depends(journal_queries_sync),
) -> JournalListResponse:
    """Liste paginée des revues avec comptage des publications rattachées.

    `search` : recherche insensible à la casse sur le titre normalisé,
    ignorée si < 2 caractères. `publisher_id` : filtre par éditeur.
    `sort` : `title` / `-title` / `publisher` / `-publisher` /
    `pubs` / `-pubs` ; fallback sur `title` si valeur inconnue.
    """
    return queries.list_journals(
        search=search,
        publisher_id=publisher_id,
        sort=sort,
        page=page,
        per_page=per_page,
    )


@router.get("/api/journals/{journal_id}", response_model=JournalBasic)
def get_journal(
    journal_id: int,
    queries: JournalQueries = Depends(journal_queries_sync),
) -> JournalBasic:
    """Récupère une revue par son id (titre uniquement). 404 si inconnue."""
    row = queries.get_journal(journal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Revue introuvable")
    return row


@router.put("/api/journals/{journal_id}", response_model=OkResponse)
def update_journal(
    journal_id: int,
    body: JournalUpdate,
    repo: JournalRepository = Depends(journal_repo_sync),
) -> OkResponse:
    """Met à jour une revue (modification sélective des champs fournis).

    Seuls les champs explicitement présents dans le body sont écrits
    (`exclude_unset=True`). Lève 404 si la revue n'existe pas.
    """
    fields = body.model_dump(exclude_unset=True)
    _update_journal(journal_id, fields=fields, repo=repo)
    return OkResponse()


@router.post("/api/journals/{journal_id}/merge", response_model=MergeResponse)
def merge(
    journal_id: int,
    body: MergeRequest,
    queries: JournalQueries = Depends(journal_queries_sync),
    repo: JournalRepository = Depends(journal_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> MergeResponse:
    """Fusionne la revue `source_id` dans la revue `journal_id`.

    Les publications et métadonnées de la source sont transférées à
    la cible ; la source est supprimée. 404 si l'une des deux est
    introuvable.
    """
    found = queries.existing_journal_ids((journal_id, body.source_id))
    if journal_id not in found:
        raise HTTPException(status_code=404, detail="Revue cible introuvable")
    if body.source_id not in found:
        raise HTTPException(status_code=404, detail="Revue source introuvable")

    merge_journals(journal_id, body.source_id, repo=repo, audit_repo=audit)
    return MergeResponse(merged=True, source_id=body.source_id, target_id=journal_id)
