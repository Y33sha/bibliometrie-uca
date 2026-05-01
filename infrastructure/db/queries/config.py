"""Query services pour les paramètres applicatifs (table `config`).

Lookups par clé pour l'application (extraction, OA email, etc.) restent
dans `infrastructure/app_config.py` ; ce module héberge les queries
servies par le router admin (listing complet pour édition).
"""

from typing import Any


async def list_config_async(cur: Any) -> list[dict[str, Any]]:
    """Tous les paramètres applicatifs triés par clé."""
    await cur.execute("SELECT key, value, description, updated_at FROM config ORDER BY key")
    return await cur.fetchall()
