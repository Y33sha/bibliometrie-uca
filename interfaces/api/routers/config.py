"""Router des paramètres clé-valeur du pipeline. Sert `/api/config/*`.

La table `config` porte les réglages d'exploitation : années couvertes, choix des périmètres par phase, types de structure affichés. La définition des périmètres eux-mêmes appartient au router `perimeters.py`.
"""

from typing import cast

from fastapi import APIRouter, Depends

from application.services.config import ConfigService
from domain.users import SessionUser
from infrastructure.read_models.config.models import (
    ConfigItem,
)
from infrastructure.read_models.config.queries import ConfigQueries
from infrastructure.read_models.perimeters.models import (
    InstitutionOut,
)
from infrastructure.read_models.perimeters.queries import PerimetersQueries
from interfaces.api.deps import (
    config_queries,
    config_service,
    perimeters_queries,
    session_user,
)
from interfaces.api.models import ConfigValueUpdate

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", response_model=list[ConfigItem])
def list_config(
    user: SessionUser | None = Depends(session_user),
    queries: ConfigQueries = Depends(config_queries),
) -> list[ConfigItem]:
    """Paramètres applicatifs (clé, valeur JSON, description), triés par clé.

    Sans le rôle admin, la lecture se restreint à la liste blanche `PUBLIC_CONFIG_KEYS` ; une clé qu'on n'y inscrit pas reste réservée.
    """
    return queries.list_config(public_only=user is None or not user.is_admin)


@router.get("/institution", response_model=InstitutionOut)
def institution(queries: PerimetersQueries = Depends(perimeters_queries)) -> InstitutionOut:
    """Établissement servi par l'instance : nom et structures racines du périmètre des personnes, titre de l'application."""
    return queries.institution()


@router.put("/{key}", response_model=ConfigItem)
def update_config(
    key: str,
    body: ConfigValueUpdate,
    config: ConfigService = Depends(config_service),
) -> ConfigItem:
    """Met à jour la valeur d'un paramètre applicatif.

    L'écriture exige une session : le middleware garde toutes les méthodes autres que `GET`. La clé doit préexister — les clés sont déclarées dans les migrations, cet endpoint n'en crée pas —, et une clé inconnue rend 404.
    """
    row = config.update_config_value(key, body.value)
    return ConfigItem(
        key=cast(str, row["key"]),
        value=row["value"],
        description=cast("str | None", row["description"]),
    )
