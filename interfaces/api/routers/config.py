"""Configuration router — paramètres applicatifs clé/valeur.

La table `config` stocke des paramètres globaux (années pipeline, clés
API, credentials sources, etc.). Les périmètres (table `perimeters`)
sont dans le router dédié `perimeters.py`.
"""

import logging
from typing import Any

from fastapi import APIRouter

from application import config as config_service
from infrastructure.repositories import async_config_repository
from interfaces.api.async_deps import get_async_cursor
from interfaces.api.models import ConfigItem, ConfigValueUpdate, HalCollectionsResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/config", response_model=list[ConfigItem])
async def list_config() -> Any:
    """Liste tous les paramètres applicatifs (clé, valeur JSON, description).

    Retourne la table `config` triée par clé. Les valeurs sont
    renvoyées telles quelles (jsonb) — la sémantique de chaque clé
    est documentée dans `docs/exploitation.md`.
    """
    async with get_async_cursor() as (cur, _conn):
        await cur.execute("SELECT key, value, description, updated_at FROM config ORDER BY key")
        return await cur.fetchall()


@router.get("/api/config/hal-collections", response_model=HalCollectionsResponse)
async def get_hal_collections() -> Any:
    """Retourne les collections HAL dérivées des structures du périmètre UCA."""
    async with get_async_cursor() as (cur, _conn):
        from infrastructure.app_config import async_get_hal_collections

        collections = await async_get_hal_collections(cur)
        return {"collections": collections, "count": len(collections)}


@router.put("/api/config/{key}", response_model=ConfigItem)
async def update_config(key: str, body: ConfigValueUpdate) -> Any:
    """Met à jour la valeur d'un paramètre de config.

    La clé doit préexister (pas de création via cet endpoint — les
    clés sont déclarées dans les migrations). 404 si la clé est
    inconnue.
    """
    async with get_async_cursor() as (cur, _conn):
        return await config_service.update_config_value(
            cur, key, body.value, repo=async_config_repository(cur)
        )
