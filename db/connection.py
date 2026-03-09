"""
Utilitaire de connexion PostgreSQL.
"""

import psycopg2
from psycopg2.extras import Json, execute_values
import sys
import os

# Ajouter la racine du projet au path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import DB


def get_connection():
    """Retourne une connexion psycopg2 vers la base publisher-stats."""
    return psycopg2.connect(**DB)
