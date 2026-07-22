"""Résolution id → libellé d'une entité de facette (`/api/entity-labels`).

Seed via un pool dédié en autocommit, hors du pool partagé par l'API, avec un nettoyage en fin de module — même stratégie que les autres tests de routers.
"""

import os
import uuid
from contextlib import contextmanager

import psycopg
import pytest
from psycopg.rows import dict_row

_DB_ARGS = {
    "dbname": "bibliometrie_test",
    "user": os.environ["DB_USER"],
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "5432")),
}
if os.environ.get("DB_PASSWORD"):
    _DB_ARGS["password"] = os.environ["DB_PASSWORD"]


@contextmanager
def _pool():
    conn = psycopg.connect(**_DB_ARGS, row_factory=dict_row)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    yield
    with _pool() as cur:
        cur.execute("TRUNCATE TABLE journals, publishers RESTART IDENTITY CASCADE")


class TestEntityLabels:
    def test_unknown_id(self, client):
        """Un id absent rend un libellé nul, non une erreur : la pastille reste sans nom."""
        r = client.get("/api/entity-labels", params={"kind": "journal", "entity_id": 999999999})
        assert r.status_code == 200
        assert r.json() == {"label": None}

    def test_journal_reads_its_title(self, client):
        title = f"Revue {uuid.uuid4().hex[:8]}"
        with _pool() as cur:
            cur.execute(
                "INSERT INTO journals (title, title_normalized) VALUES (%s, lower(%s)) RETURNING id",
                (title, title),
            )
            journal_id = cur.fetchone()["id"]
        r = client.get("/api/entity-labels", params={"kind": "journal", "entity_id": journal_id})
        assert r.json() == {"label": title}

    def test_publisher_reads_its_name(self, client):
        """Le libellé d'un éditeur se lit dans `name`, là où celui d'une revue se lit dans `title`."""
        name = f"Editeur {uuid.uuid4().hex[:8]}"
        with _pool() as cur:
            cur.execute(
                "INSERT INTO publishers (name, name_normalized) VALUES (%s, lower(%s)) RETURNING id",
                (name, name),
            )
            publisher_id = cur.fetchone()["id"]
        r = client.get(
            "/api/entity-labels", params={"kind": "publisher", "entity_id": publisher_id}
        )
        assert r.json() == {"label": name}

    def test_unknown_kind_rejected(self, client):
        r = client.get("/api/entity-labels", params={"kind": "person", "entity_id": 1})
        assert r.status_code == 422
