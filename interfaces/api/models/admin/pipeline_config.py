"""Modèles Pydantic du router de configuration du pipeline : corps des requêtes entrantes."""

from typing import Any

from pydantic import BaseModel


class ConfigValueUpdate(BaseModel):
    """Corps de PUT /api/config/{key} : value JSON-sérialisable arbitraire."""

    # `Any` plutôt que `JsonValue` (récursif PEP 695) : le schéma JSON
    # généré contient une self-référence que `openapi-typescript` n'arrive
    # pas à instancier côté TS (cf. `application/ports/api/config_queries.py`).
    value: Any
