"""Router des paramètres clé-valeur du pipeline. Sert `/api/config/*`.

La table `config` porte les réglages globaux : années couvertes, identifiants d'accès aux sources, choix des périmètres par phase. La définition des périmètres eux-mêmes appartient au router `perimeters.py`.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from application.ports.api.config_queries import ConfigItem, ConfigQueries
from application.ports.config import ConfigStore
from application.services.config import commands as config_commands
from interfaces.api.deps import config_queries, config_store, current_admin_user, db_conn
from interfaces.api.models import ConfigValueUpdate

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", response_model=list[ConfigItem])
def list_config(
    admin_user: str | None = Depends(current_admin_user),
    queries: ConfigQueries = Depends(config_queries),
) -> list[ConfigItem]:
    """Paramètres applicatifs (clé, valeur JSON, description), triés par clé.

    La table porte deux natures de réglages : des paramètres d'exploitation que les pages publiques consomment, et les identifiants d'accès aux sources — clés d'API OpenAlex et Web of Science, compte ScanR, adresse du polite pool. Sans session, la lecture se restreint donc à la liste blanche `PUBLIC_CONFIG_KEYS` ; une clé qu'on n'y inscrit pas reste réservée.
    """
    return queries.list_config(public_only=admin_user is None)


@router.put("/{key}", response_model=ConfigItem)
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
