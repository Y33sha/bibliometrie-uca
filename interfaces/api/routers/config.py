"""Router des paramètres clé-valeur du pipeline. Sert `/api/config/*`.

La table `config` porte les réglages globaux : années couvertes, identifiants d'accès aux sources, choix des périmètres par phase. La définition des périmètres eux-mêmes appartient au router `perimeters.py`.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from application.ports.api.config_queries import ConfigItem, ConfigQueries
from application.ports.config import ConfigStore
from application.services.config import commands as config_commands
from interfaces.api.deps import config_queries, config_store, db_conn, require_admin
from interfaces.api.models import ConfigValueUpdate

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", response_model=list[ConfigItem], dependencies=[Depends(require_admin)])
def list_config(
    queries: ConfigQueries = Depends(config_queries),
) -> list[ConfigItem]:
    """Liste tous les paramètres applicatifs (clé, valeur JSON, description).

    Rend la table `config` triée par clé, valeurs comprises. Parmi elles figurent les identifiants d'accès aux sources — clés d'API OpenAlex et Web of Science, compte ScanR — d'où l'authentification exigée : c'est la seule lecture de l'API qui livre des secrets, et la garde par méthode HTTP du middleware ne couvre que les écritures.
    """
    return queries.list_config()


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
