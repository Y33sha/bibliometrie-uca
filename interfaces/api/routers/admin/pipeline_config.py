"""Router /api/config/* — les paramètres clé-valeur du pipeline.

La table `config` porte les réglages globaux : années couvertes, identifiants d'accès aux sources, choix des périmètres par phase. La définition des périmètres eux-mêmes appartient au router `admin/perimeters.py`.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from application.ports.api.config_queries import ConfigItem, ConfigQueries
from application.ports.config import ConfigStore
from application.services.config import commands as config_commands
from interfaces.api.deps import config_queries, config_store, db_conn
from interfaces.api.models import ConfigValueUpdate

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/config", response_model=list[ConfigItem])
def list_config(
    queries: ConfigQueries = Depends(config_queries),
) -> list[ConfigItem]:
    """Liste tous les paramètres applicatifs (clé, valeur JSON, description).

    Retourne la table `config` triée par clé. Les valeurs sont renvoyées telles quelles (jsonb) — la sémantique de chaque clé est documentée dans `docs/exploitation.md`.
    """
    return queries.list_config()


@router.put("/api/config/{key}", response_model=ConfigItem)
def update_config(
    key: str,
    body: ConfigValueUpdate,
    conn: Connection = Depends(db_conn),
    config_repo: ConfigStore = Depends(config_store),
) -> ConfigItem:
    """Met à jour la valeur d'un paramètre de config.

    La clé doit préexister (pas de création via cet endpoint — les clés sont déclarées dans les migrations). 404 si la clé est inconnue.
    """
    return ConfigItem.model_validate(
        config_commands.update_config_value(conn, key, body.value, config=config_repo)
    )
