"""Configuration router — paramètres applicatifs clé/valeur.

La table `config` stocke des paramètres globaux (années pipeline, clés
API, credentials sources, etc.). Les périmètres (table `perimeters`)
sont dans le router dédié `perimeters.py`.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from application import config as config_service
from application.ports.config import ConfigStore
from application.ports.config_queries import ConfigQueries
from interfaces.api.deps import config_queries_sync, config_store_sync, db_conn_sync
from interfaces.api.models import ConfigItem, ConfigValueUpdate, HalCollectionsResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/config", response_model=list[ConfigItem])
def list_config(
    queries: ConfigQueries = Depends(config_queries_sync),
) -> Any:
    """Liste tous les paramètres applicatifs (clé, valeur JSON, description).

    Retourne la table `config` triée par clé. Les valeurs sont
    renvoyées telles quelles (jsonb) — la sémantique de chaque clé
    est documentée dans `docs/exploitation.md`.
    """
    return queries.list_config()


@router.get("/api/config/hal-collections", response_model=HalCollectionsResponse)
def get_hal_collections(
    queries: ConfigQueries = Depends(config_queries_sync),
) -> Any:
    """Retourne les collections HAL dérivées des structures du périmètre."""
    collections = queries.get_hal_collections()
    return {"collections": collections, "count": len(collections)}


@router.put("/api/config/{key}", response_model=ConfigItem)
def update_config(
    key: str,
    body: ConfigValueUpdate,
    conn: Connection = Depends(db_conn_sync),
    config_repo: ConfigStore = Depends(config_store_sync),
) -> Any:
    """Met à jour la valeur d'un paramètre de config.

    La clé doit préexister (pas de création via cet endpoint — les
    clés sont déclarées dans les migrations). 404 si la clé est
    inconnue.
    """
    return config_service.update_config_value(conn, key, body.value, config=config_repo)
