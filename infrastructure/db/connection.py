"""
Utilitaire de connexion PostgreSQL.
"""

import os

import psycopg2

from infrastructure.settings import settings

SANDBOX_DB_NAME = "bibliometrie_sandbox"


def get_connection():
    """Retourne une connexion psycopg2.

    Si la variable d'environnement BIBLIOMETRIE_SANDBOX=1 est définie,
    se connecte à la base sandbox au lieu de la base principale.
    """
    db_args = settings.db_args
    if os.environ.get("BIBLIOMETRIE_SANDBOX") == "1":
        db_args["dbname"] = SANDBOX_DB_NAME
    return psycopg2.connect(**db_args)
