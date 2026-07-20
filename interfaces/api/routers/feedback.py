"""Router de la qualité de la détection des structures dans les adresses. Sert `/api/feedback/*`.

Alimente le tableau de bord qui confronte la détection automatique aux arbitrages manuels : taux de détection, faux négatifs (adresses confirmées à la main mais non détectées) et faux positifs (adresses détectées mais rejetées à la main). Les trois lectures portent sur une structure, que l'appelant désigne — il la choisit dans `/api/structures`.
"""

from fastapi import APIRouter, Depends, Query

from application.ports.api.feedback_queries import (
    FeedbackAddressesResponse,
    FeedbackQueries,
    FeedbackStats,
)
from interfaces.api.deps import feedback_queries

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


@router.get("/stats", response_model=FeedbackStats)
def feedback_stats(
    structure_id: int = Query(...),
    queries: FeedbackQueries = Depends(feedback_queries),
) -> FeedbackStats:
    """Statistiques de qualité de la détection pour une structure donnée."""
    return queries.feedback_stats(structure_id)


@router.get("/false-negatives", response_model=FeedbackAddressesResponse)
def feedback_false_negatives(
    structure_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str = Query(""),
    queries: FeedbackQueries = Depends(feedback_queries),
) -> FeedbackAddressesResponse:
    """Adresses confirmées manuellement pour cette structure mais non détectées par le script."""
    return queries.feedback_false_negatives(
        structure_id=structure_id, page=page, per_page=per_page, search=search
    )


@router.get("/false-positives", response_model=FeedbackAddressesResponse)
def feedback_false_positives(
    structure_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str = Query(""),
    queries: FeedbackQueries = Depends(feedback_queries),
) -> FeedbackAddressesResponse:
    """Adresses détectées pour cette structure mais rejetées manuellement."""
    return queries.feedback_false_positives(
        structure_id=structure_id, page=page, per_page=per_page, search=search
    )
