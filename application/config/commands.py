"""Command handlers des écritures API sur la config : la frontière transactionnelle.

Une écriture API est une commande (intention courte d'un acteur). Le handler
reçoit la connexion de la requête, compose la brique agnostique de `core.py` et
`conn.commit()` au succès — pour que la donnée soit persistée avant l'envoi de la
réponse (cf. `docs/chantiers/CODE_commit-avant-reponse.md`).
"""

from sqlalchemy import Connection

from application.config import core as config_service
from application.ports.config import ConfigStore
from domain.types import JsonValue


def update_config_value(
    conn: Connection,
    key: str,
    value: JsonValue,
    *,
    config: ConfigStore,
) -> dict[str, JsonValue]:
    """Met à jour la valeur d'un paramètre de config existant. Retourne la ligne mise à jour."""
    row = config_service.update_config_value(key, value, config=config)
    conn.commit()
    return row
