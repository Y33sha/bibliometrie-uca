"""Router Revues — liste, recherche, fusion, types."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from application.journals import merge_journals
from application.journals import update_journal as _update_journal
from application.ports.api.journals_queries import (
    JournalDashboardResponse,
    JournalDetailResponse,
    JournalListResponse,
    JournalQueries,
)
from application.ports.api.subjects_queries import SubjectFrequency
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository
from domain.journals.journal import JOURNAL_TYPES
from interfaces.api.deps import (
    audit_repo_sync,
    journal_queries_sync,
    journal_repo_sync,
)
from interfaces.api.models import (
    EnumOption,
    JournalUpdate,
    MergeRequest,
    MergeResponse,
    OkResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# Mapping value enum → label FR (concern UI, donc côté router/interfaces, pas domain).
_JOURNAL_TYPE_LABELS_FR: dict[str, str] = {
    "journal": "Revue",
    "proceedings": "Proceedings",
    "repository": "Archive / dépôt",
    "book_series": "Série d'ouvrages",
    "preprint_server": "Serveur de preprints",
    "media": "Média",
}


@router.get("/api/journal-types", response_model=list[EnumOption])
def list_journal_types() -> list[EnumOption]:
    """Valeurs possibles de l'enum `journal_type` avec leur label français.

    Source de vérité côté Python : `domain.journals.journal.JOURNAL_TYPES`
    (test d'intégration `TestJournalTypesEnum` vérifie la cohérence avec l'enum SQL).
    Sert à alimenter le dropdown de la page admin revues.
    """
    return [EnumOption(value=v, label_fr=_JOURNAL_TYPE_LABELS_FR[v]) for v in JOURNAL_TYPES]


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


@router.get("/api/journals/{journal_id}", response_model=JournalDetailResponse)
def get_journal(
    journal_id: int,
    queries: JournalQueries = Depends(journal_queries_sync),
) -> JournalDetailResponse:
    """Profil complet d'une revue pour la page publique `/journals/[id]`.

    Inclut métadonnées + payload DOAJ brut + date d'import DOAJ + nombre de
    publications rattachées. 404 si la revue est inconnue.
    """
    row = queries.get_journal_detail(journal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Revue introuvable")
    return row


@router.get("/api/journals/{journal_id}/dashboard", response_model=JournalDashboardResponse)
def get_journal_dashboard(
    journal_id: int,
    queries: JournalQueries = Depends(journal_queries_sync),
) -> JournalDashboardResponse:
    """Agrégats des publications de la revue (distribution `doc_type` + `oa_status`).

    Sert l'onglet « Dashboard » de la page publique d'une revue pour repérer
    visuellement les incohérences (ex. `article` sur un journal_type
    `proceedings`). 404 si la revue est inconnue.
    """
    result = queries.get_journal_dashboard(journal_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Revue introuvable")
    return result


@router.get("/api/journals/{journal_id}/subjects", response_model=list[SubjectFrequency])
def get_journal_subjects(
    journal_id: int,
    limit: int = Query(30, ge=1, le=200),
    queries: JournalQueries = Depends(journal_queries_sync),
) -> list[SubjectFrequency]:
    """Top sujets des publications de la revue (pour l'onglet Dashboard).

    Exclut les sujets trop génériques (`usage_count > 5000`) pour ne pas
    noyer le top-N. Retourne une liste vide si la revue existe sans
    publications taggées (pas de 404 pour rester idempotent à l'usage UI).
    """
    return queries.get_journal_subjects(journal_id, limit=limit)


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
