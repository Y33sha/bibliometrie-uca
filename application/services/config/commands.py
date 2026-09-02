"""Command handlers des écritures API sur la table `config` : frontière transactionnelle.

Écriture triviale, servie par le port `ConfigRepository` sans brique agnostique séparée.
"""

from sqlalchemy import Connection

from application.audit_log import emit_event
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.config_repository import ConfigRepository
from domain.errors import NotFoundError
from domain.types import JsonValue


def update_config_value(
    conn: Connection,
    key: str,
    value: JsonValue,
    *,
    config: ConfigRepository,
    audit_repo: AuditRepository | None = None,
) -> dict[str, JsonValue]:
    """Met à jour la valeur d'un paramètre de config existant. `value` est sérialisé en JSON. Retourne la ligne mise à jour ; lève `NotFoundError` si la clé n'existe pas.

    Un réglage d'exploitation change le comportement de l'application sans rien changer aux données : le changement ne se relit nulle part ensuite, d'où l'événement d'audit. La clé étant un texte, elle vit dans la charge utile, l'identifiant d'agrégat n'accueillant qu'un entier. La valeur antérieure n'y figure pas : le journal la porte déjà, sous la forme de l'événement qui l'a posée.
    """
    row = config.update_config_value(key, value)
    if row is None:
        raise NotFoundError(f"Paramètre '{key}' introuvable")
    emit_event(audit_repo, "config.updated", "config", None, {"key": key, "value": value})
    conn.commit()
    return row
