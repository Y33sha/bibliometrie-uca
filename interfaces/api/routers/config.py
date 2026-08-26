"""Router des paramètres clé-valeur du pipeline. Sert `/api/config/*`.

La table `config` porte les réglages d'exploitation : années couvertes, choix des périmètres par phase, types de structure affichés. La définition des périmètres eux-mêmes appartient au router `perimeters.py`.
"""

from typing import cast

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from application.ports.read_models.config_queries import ConfigItem, ConfigQueries
from application.ports.repositories.config_repository import ConfigRepository
from application.services.config import commands as config_commands
from interfaces.api.deps import admin_user_or_none, config_queries, config_repository, db_conn
from interfaces.api.models import ConfigValueUpdate

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", response_model=list[ConfigItem])
def list_config(
    admin_user: str | None = Depends(admin_user_or_none),
    queries: ConfigQueries = Depends(config_queries),
) -> list[ConfigItem]:
    """Paramètres applicatifs (clé, valeur JSON, description), triés par clé.

    Sans session, la lecture se restreint à la liste blanche `PUBLIC_CONFIG_KEYS` ; une clé qu'on n'y inscrit pas reste réservée.
    """
    return queries.list_config(public_only=admin_user is None)


@router.put("/{key}", response_model=ConfigItem)
def update_config(
    key: str,
    body: ConfigValueUpdate,
    conn: Connection = Depends(db_conn),
    config: ConfigRepository = Depends(config_repository),
) -> ConfigItem:
    """Met à jour la valeur d'un paramètre applicatif.

    L'écriture exige une session : le middleware garde toutes les méthodes autres que `GET`. La clé doit préexister — les clés sont déclarées dans les migrations, cet endpoint n'en crée pas —, et une clé inconnue rend 404.
    """
    row = config_commands.update_config_value(conn, key, body.value, config=config)
    return ConfigItem(
        key=cast(str, row["key"]),
        value=row["value"],
        description=cast("str | None", row["description"]),
    )
