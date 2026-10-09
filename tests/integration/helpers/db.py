"""Connexion à la base de test sous le propriétaire du schéma.

Les tests d'intégration de l'API montent leur jeu de données au niveau du module, avant que les fixtures de pytest n'existent, et créent des lignes dans toutes les tables. Ce gestionnaire de contexte leur ouvre un curseur sous le propriétaire, en validation immédiate : ce qu'un module sème est visible du serveur d'API que le test interroge.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
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


def truncate_after_module(*tables: str, then: Sequence[str] = ()) -> Callable[[], Iterator[None]]:
    """Fixture de module qui vide `tables` à la fin du module, puis exécute les instructions `then`.

    Les écritures des tests d'API sont validées dans la base : le module les retire pour ne pas peser sur les suites suivantes. S'emploie au niveau du module : `_cleanup_after_module = truncate_after_module("structures")`.
    """

    @pytest.fixture(scope="module", autouse=True)
    def _truncate() -> Iterator[None]:
        yield
        with owner_pool() as cur:
            cur.execute(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE")
            for statement in then:
                cur.execute(statement)

    return _truncate
