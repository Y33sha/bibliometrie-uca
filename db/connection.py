"""
Utilitaire de connexion PostgreSQL.
"""

import psycopg2
from psycopg2.extras import Json, execute_values
import os

# Ajouter la racine du projet au path
from config.settings import DB

SANDBOX_DB_NAME = "bibliometrie_sandbox"


def get_connection():
    """Retourne une connexion psycopg2.

    Si la variable d'environnement BIBLIOMETRIE_SANDBOX=1 est définie,
    se connecte à la base sandbox au lieu de la base principale.
    """
    db_args = dict(DB)
    if os.environ.get("BIBLIOMETRIE_SANDBOX") == "1":
        db_args["dbname"] = SANDBOX_DB_NAME
    return psycopg2.connect(**db_args)
