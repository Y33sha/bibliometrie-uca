"""Configuration router — paramètres applicatifs clé/valeur.

La table `config` stocke des paramètres globaux (années pipeline, clés
API, credentials sources, etc.). Les périmètres (table `perimeters`)
sont dans le router dédié `perimeters.py`.
"""

import logging

from fastapi import APIRouter, Depends

from application import config as config_service
from application.ports.config import ConfigStore
from application.ports.config_queries import ConfigQueries
from interfaces.api.deps import config_queries_sync, config_store_sync
from interfaces.api.models import ConfigItem, ConfigValueUpdate, HalCollectionsResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/config", response_model=list[ConfigItem])
def list_config(
    queries: ConfigQueries = Depends(config_queries_sync),
) -> list[ConfigItem]:
    """Liste tous les paramètres applicatifs (clé, valeur JSON, description).

    Retourne la table `config` triée par clé. Les valeurs sont
    renvoyées telles quelles (jsonb) — la sémantique de chaque clé
    est documentée dans `docs/exploitation.md`.
    """
    return [ConfigItem.model_validate(r) for r in queries.list_config()]


@router.get("/api/config/hal-collections", response_model=HalCollectionsResponse)
def get_hal_collections(
    queries: ConfigQueries = Depends(config_queries_sync),
) -> HalCollectionsResponse:
    """Retourne les collections HAL dérivées des structures du périmètre."""
    collections = queries.get_hal_collections()
    return HalCollectionsResponse(collections=collections, count=len(collections))


@router.put("/api/config/{key}", response_model=ConfigItem)
def update_config(
    key: str,
    body: ConfigValueUpdate,
    config_repo: ConfigStore = Depends(config_store_sync),
) -> ConfigItem:
    """Met à jour la valeur d'un paramètre de config.

    La clé doit préexister (pas de création via cet endpoint — les
    clés sont déclarées dans les migrations). 404 si la clé est
    inconnue.
    """
    return ConfigItem.model_validate(
        config_service.update_config_value(key, body.value, config=config_repo)
    )
