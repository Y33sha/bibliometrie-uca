"""Configuration router — paramètres applicatifs clé/valeur.

La table `config` stocke des paramètres globaux (années pipeline, clés
API, credentials sources, etc.). Les périmètres (table `perimeters`)
sont dans le router dédié `perimeters.py`.
"""

import logging
from typing import Any

from fastapi import APIRouter

from application import config as config_service
from infrastructure.repositories import config_repository
from interfaces.api.deps import get_cursor
from interfaces.api.models import ConfigValueUpdate

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/config")
async def list_config() -> Any:
    with get_cursor() as (cur, _conn):
        cur.execute("SELECT key, value, description, updated_at FROM config ORDER BY key")
        return cur.fetchall()


@router.get("/api/config/hal-collections")
async def get_hal_collections() -> Any:
    """Retourne les collections HAL dérivées des structures du périmètre UCA."""
    with get_cursor() as (cur, _conn):
        from infrastructure.app_config import get_hal_collections as _get

        collections = _get(cur)
        return {"collections": collections, "count": len(collections)}


@router.put("/api/config/{key}")
async def update_config(key: str, body: ConfigValueUpdate) -> Any:
    with get_cursor() as (cur, _conn):
        return config_service.update_config_value(
            cur, key, body.value, repo=config_repository(cur)
        )
