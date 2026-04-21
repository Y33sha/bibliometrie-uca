"""Router /api/authorships/* — délègue à infrastructure/db/queries/authorships.py."""

import logging
from typing import Any

from fastapi import APIRouter, Query

from infrastructure.db.queries import authorships as auth_queries
from interfaces.api.deps import get_cursor
from interfaces.api.models import (
    AuthorshipsFacets,
    AuthorshipsListResponse,
    AuthorshipsStats,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/authorships/stats", response_model=AuthorshipsStats)
async def authorships_stats(lab_id: int = Query(0)) -> Any:
    """Compteurs globaux des authorships UCA (total, rattachées à une
    personne, avec ORCID/idHAL).

    `lab_id=0` (défaut) = périmètre UCA complet ; sinon restreint
    au laboratoire donné.
    """
    with get_cursor() as (cur, _conn):
        return auth_queries.authorships_stats(cur, lab_id)


@router.get("/api/authorships/facets", response_model=AuthorshipsFacets)
async def authorships_facets(
    linked: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    lab_id: int = Query(0),
) -> Any:
    """Facettes dynamiques (compteurs par valeur) pour la page admin authorships.

    Chaque facette est calculée en « skip filter » : elle exclut le
    filtre homonyme actif pour que l'utilisateur voie toujours les
    autres valeurs disponibles. Paramètres `yes`/`no`/empty comme pour
    le endpoint de liste.
    """
    with get_cursor() as (cur, _conn):
        return auth_queries.authorships_facets(
            cur, linked=linked, has_orcid=has_orcid, has_idhal=has_idhal, lab_id=lab_id
        )


@router.get("/api/authorships", response_model=AuthorshipsListResponse)
async def list_authorships(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    linked: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    lab_id: int = Query(0),
) -> Any:
    """Liste paginée des authorships UCA avec filtres admin.

    `search` : portion de nom auteur (case/accent-insensible).
    `linked=yes|no` : avec/sans person_id rattaché.
    `has_orcid=yes|no`, `has_idhal=yes|no` : présence de ces
    identifiants sur la personne liée. `lab_id=0` = pas de
    restriction laboratoire.
    """
    with get_cursor() as (cur, _conn):
        return auth_queries.list_authorships(
            cur,
            search=search,
            linked=linked,
            has_orcid=has_orcid,
            has_idhal=has_idhal,
            lab_id=lab_id,
            page=page,
            per_page=per_page,
        )
