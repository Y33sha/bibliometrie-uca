"""Connexion à la base de test sous le propriétaire du schéma.

Les tests d'intégration de l'API montent leur jeu de données au niveau du module, avant que les fixtures de pytest n'existent, et créent des lignes dans toutes les tables. Ce gestionnaire de contexte leur ouvre un curseur sous le propriétaire, en validation immédiate : ce qu'un module sème est visible du serveur d'API que le test interroge.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

_ARGS: dict[str, Any] = {
    "dbname": "bibliometrie_test",
    "user": os.environ["DB_OWNER_USER"],
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "5432")),
}
if os.environ.get("DB_OWNER_PASSWORD"):
    _ARGS["password"] = os.environ["DB_OWNER_PASSWORD"]


@contextmanager
def owner_pool() -> Iterator[psycopg.Cursor[dict[str, Any]]]:
    """Curseur sur la base de test, en validation immédiate, fermé à la sortie."""
    conn = psycopg.connect(**_ARGS, row_factory=dict_row)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()
