"""Router admin feedback : diagnostics qualité de la détection d'adresses.

Expose les endpoints `/api/admin/feedback/*` qui servent le tableau de bord qualité : taux de détection global, liste des faux négatifs (adresses confirmées manuellement mais non détectées par le script) et faux positifs (adresses détectées mais rejetées manuellement).

L'endpoint `feedback_rerun` reste `async def` : il pilote un sous-processus en streaming SSE (asyncio), incompatible avec un threadpool sync. FastAPI sait cohabiter `def` et `async def` dans le même router.
"""

import logging
import os
import sys
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from application.ports.api.admin_feedback_queries import AdminFeedbackQueries
from interfaces.api.deps import admin_feedback_queries_sync
from interfaces.api.models import (
    FeedbackAddressesResponse,
    FeedbackStats,
    FeedbackStructureItem,
    FeedbackStructuresResponse,
)

# Types de structures éligibles au tableau de bord feedback, dans l'ordre
# d'affichage (universités en premier, laboratoires en dernier). Règle
# métier : le feedback porte sur les entités organisationnelles de
# haut niveau, pas sur les sites physiques ni les équipes internes.
_FEEDBACK_STRUCTURE_TYPES: tuple[str, ...] = (
    "universite",
    "onr",
    "chu",
    "ecole",
    "labo",
)

# Code de la structure par défaut (UCA = tenant du projet).
_DEFAULT_STRUCTURE_CODE = "uca"

router = APIRouter()
logger = logging.getLogger(__name__)

_RESOLVE_ADDRESSES_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "processing",
    "resolve_addresses.py",
)


@router.get("/api/admin/feedback/structures", response_model=FeedbackStructuresResponse)
def feedback_structures(
    queries: AdminFeedbackQueries = Depends(admin_feedback_queries_sync),
) -> FeedbackStructuresResponse:
    """Structures éligibles au tableau de bord feedback, groupées par type.

    Encode deux règles métier :
    - seuls les types listés dans `_FEEDBACK_STRUCTURE_TYPES` sont
      éligibles (universités, organismes, CHU, écoles, labos) ;
    - la structure UCA (code = "uca") est sélectionnée par défaut si
      elle existe, sinon la première structure du premier type non vide.
    """
    rows = queries.feedback_structures(list(_FEEDBACK_STRUCTURE_TYPES))

    by_type: dict[str, list[FeedbackStructureItem]] = {}
    default_id: int | None = None
    for row in rows:
        by_type.setdefault(row["type"], []).append(FeedbackStructureItem(**row))
        if row["code"] == _DEFAULT_STRUCTURE_CODE:
            default_id = row["id"]

    if default_id is None:
        # Fallback : première structure du premier type non vide, dans
        # l'ordre `_FEEDBACK_STRUCTURE_TYPES`.
        for t in _FEEDBACK_STRUCTURE_TYPES:
            if by_type.get(t):
                default_id = by_type[t][0].id
                break

    return FeedbackStructuresResponse(by_type=by_type, default_structure_id=default_id)


@router.get("/api/admin/feedback/stats", response_model=FeedbackStats)
def feedback_stats(
    structure_id: int = Query(...),
    queries: AdminFeedbackQueries = Depends(admin_feedback_queries_sync),
) -> FeedbackStats:
    """Statistiques de qualité de la détection pour une structure donnée."""
    row = queries.feedback_stats(structure_id)

    reviewed = (
        (row["concordant_valid"] or 0)
        + (row["concordant_rejected"] or 0)
        + (row["false_negatives"] or 0)
        + (row["false_positives"] or 0)
    )
    concordant = (row["concordant_valid"] or 0) + (row["concordant_rejected"] or 0)

    return FeedbackStats(
        total_reviewed=reviewed,
        detection_rate=round(concordant / reviewed * 100, 1) if reviewed else None,
        false_negatives=row["false_negatives"] or 0,
        false_positives=row["false_positives"] or 0,
        concordant_valid=row["concordant_valid"] or 0,
        pending=row["pending"] or 0,
    )


@router.get("/api/admin/feedback/false-negatives", response_model=FeedbackAddressesResponse)
def feedback_false_negatives(
    structure_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    queries: AdminFeedbackQueries = Depends(admin_feedback_queries_sync),
) -> FeedbackAddressesResponse:
    """Adresses confirmées manuellement pour cette structure mais non détectées par le script."""
    data = queries.feedback_false_negatives(
        structure_id=structure_id, page=page, per_page=per_page, search=search
    )
    return FeedbackAddressesResponse(**data)


@router.get("/api/admin/feedback/false-positives", response_model=FeedbackAddressesResponse)
def feedback_false_positives(
    structure_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    queries: AdminFeedbackQueries = Depends(admin_feedback_queries_sync),
) -> FeedbackAddressesResponse:
    """Adresses détectées pour cette structure mais rejetées manuellement."""
    data = queries.feedback_false_positives(
        structure_id=structure_id, page=page, per_page=per_page, search=search
    )
    return FeedbackAddressesResponse(**data)


@router.get("/api/admin/feedback/rerun")
async def feedback_rerun() -> StreamingResponse:
    """Lance resolve_addresses en SSE (détection complète sur toutes les adresses).

    `async def` parce qu'on streame stdout d'un subprocess via
    `asyncio.create_subprocess_exec` + `StreamingResponse`. Aucune
    connexion DB en jeu, cohabitation supportée par FastAPI.
    """
    import asyncio

    if not os.path.exists(_RESOLVE_ADDRESSES_SCRIPT):  # noqa: ASYNC240
        raise HTTPException(status_code=500, detail="Script resolve_addresses.py introuvable")

    async def event_stream() -> AsyncIterator[str]:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            _RESOLVE_ADDRESSES_SCRIPT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None  # subprocess créé avec stdout=PIPE
        try:
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=600)
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    yield f"data: {text}\n\n"
            returncode = await proc.wait()
            if returncode == 0:
                yield "data: [DONE]\n\n"
            else:
                yield f"data: [ERROR] Code retour {returncode}\n\n"
        except asyncio.TimeoutError:
            proc.kill()
            yield "data: [ERROR] Timeout (>10min)\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
