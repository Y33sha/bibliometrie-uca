"""Router /api/admin/feedback/* — la qualité de la détection des structures dans les adresses.

Sert le tableau de bord qui confronte la détection automatique aux arbitrages manuels : taux de détection, faux négatifs (adresses confirmées à la main mais non détectées) et faux positifs (adresses détectées mais rejetées à la main).
"""

import logging

from fastapi import APIRouter, Depends, Query

from application.ports.api.admin_feedback_queries import (
    AdminFeedbackQueries,
    FeedbackAddressesResponse,
    FeedbackStats,
    FeedbackStructureItem,
)
from interfaces.api.deps import admin_feedback_queries
from interfaces.api.models import FeedbackStructuresResponse

# Types de structures éligibles au tableau de bord feedback, dans l'ordre d'affichage (universités en premier, laboratoires en dernier).
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


@router.get("/api/admin/feedback/structures", response_model=FeedbackStructuresResponse)
def feedback_structures(
    queries: AdminFeedbackQueries = Depends(admin_feedback_queries),
) -> FeedbackStructuresResponse:
    """Structures éligibles au tableau de bord feedback, groupées par type.

    Encode deux règles métier :
    - seuls les types listés dans `_FEEDBACK_STRUCTURE_TYPES` sont éligibles (universités, organismes, CHU, écoles, labos) ;
    - la structure UCA (code = "uca") est sélectionnée par défaut si elle existe, sinon la première structure du premier type non vide.
    """
    items = queries.feedback_structures(list(_FEEDBACK_STRUCTURE_TYPES))

    by_type: dict[str, list[FeedbackStructureItem]] = {}
    default_id: int | None = None
    for item in items:
        by_type.setdefault(item.type, []).append(item)
        if item.code == _DEFAULT_STRUCTURE_CODE:
            default_id = item.id

    if default_id is None:
        # Fallback : première structure du premier type non vide, dans l'ordre `_FEEDBACK_STRUCTURE_TYPES`.
        for t in _FEEDBACK_STRUCTURE_TYPES:
            if by_type.get(t):
                default_id = by_type[t][0].id
                break

    return FeedbackStructuresResponse(by_type=by_type, default_structure_id=default_id)


@router.get("/api/admin/feedback/stats", response_model=FeedbackStats)
def feedback_stats(
    structure_id: int = Query(...),
    queries: AdminFeedbackQueries = Depends(admin_feedback_queries),
) -> FeedbackStats:
    """Statistiques de qualité de la détection pour une structure donnée."""
    return queries.feedback_stats(structure_id)


@router.get("/api/admin/feedback/false-negatives", response_model=FeedbackAddressesResponse)
def feedback_false_negatives(
    structure_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    queries: AdminFeedbackQueries = Depends(admin_feedback_queries),
) -> FeedbackAddressesResponse:
    """Adresses confirmées manuellement pour cette structure mais non détectées par le script."""
    return queries.feedback_false_negatives(
        structure_id=structure_id, page=page, per_page=per_page, search=search
    )


@router.get("/api/admin/feedback/false-positives", response_model=FeedbackAddressesResponse)
def feedback_false_positives(
    structure_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    queries: AdminFeedbackQueries = Depends(admin_feedback_queries),
) -> FeedbackAddressesResponse:
    """Adresses détectées pour cette structure mais rejetées manuellement."""
    return queries.feedback_false_positives(
        structure_id=structure_id, page=page, per_page=per_page, search=search
    )
