"""
Utilitaire de connexion PostgreSQL.
"""

import os
from typing import Any

import psycopg
from psycopg.rows import dict_row

from infrastructure.settings import settings

SANDBOX_DB_NAME = "bibliometrie_sandbox"


def get_connection() -> Any:
    """Retourne une connexion psycopg3 (rows en dict par défaut).

    Si la variable d'environnement BIBLIOMETRIE_SANDBOX=1 est définie,
    se connecte à la base sandbox au lieu de la base principale.
    """
    db_args = settings.db_args
    if os.environ.get("BIBLIOMETRIE_SANDBOX") == "1":
        db_args["dbname"] = SANDBOX_DB_NAME
    return psycopg.connect(**db_args, row_factory=dict_row)
