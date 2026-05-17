"""Tests d'intégration pour `interfaces.api.routers.admin_person_duplicates`.

Couvre :
- GET /api/admin/person-duplicates/count
- GET /api/admin/person-duplicates/next (skip param)
- POST /api/admin/person-duplicates/mark-distinct (validation, auth)
- GET /api/admin/person-duplicates/conflicts/count
- GET /api/admin/person-duplicates/conflicts/next
"""

from __future__ import annotations

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


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _seed_person(last: str | None = None, first: str | None = None) -> int:
    last = last or _uniq("Last")
    first = first or _uniq("First")
    with _pool() as cur:
        cur.execute(
            "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
            "VALUES (%s, %s, lower(%s), lower(%s)) RETURNING id",
            (last, first, last, first),
        )
        return cur.fetchone()["id"]


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    yield
    with _pool() as cur:
        cur.execute("TRUNCATE TABLE persons, distinct_persons, audit_log RESTART IDENTITY CASCADE")


class TestCountPersonDuplicates:
    def test_returns_total(self, client):
        r = client.get("/api/admin/person-duplicates/count")
        assert r.status_code == 200
        body = r.json()
        assert "total" in body
        assert isinstance(body["total"], int)


class TestNextPersonDuplicate:
    def test_returns_pair_shape(self, client):
        r = client.get("/api/admin/person-duplicates/next")
        assert r.status_code == 200
        # Sur une DB sans doublons → pair=None.
        assert "pair" in r.json()

    def test_accepts_skip_param(self, client):
        # `skip=` parsé en `set[tuple[int, int]]` ; on vérifie que la
        # query passe sans erreur et que la réponse a la bonne forme.
        r = client.get("/api/admin/person-duplicates/next", params={"skip": "1-2,3-4"})
        assert r.status_code == 200
        assert "pair" in r.json()

    def test_negative_offset_rejected(self, client):
        r = client.get("/api/admin/person-duplicates/next", params={"offset": -1})
        assert r.status_code == 422


class TestMarkPersonsDistinct:
    def test_requires_admin(self, client):
        r = client.post(
            "/api/admin/person-duplicates/mark-distinct",
            json={"person_id_a": 1, "person_id_b": 2},
        )
        assert r.status_code == 401

    def test_rejects_same_ids(self, auth_client):
        r = auth_client.post(
            "/api/admin/person-duplicates/mark-distinct",
            json={"person_id_a": 1, "person_id_b": 1},
        )
        assert r.status_code == 400
        assert "différents" in r.json()["detail"]

    def test_marks_pair_distinct(self, auth_client):
        a = _seed_person()
        b = _seed_person()
        r = auth_client.post(
            "/api/admin/person-duplicates/mark-distinct",
            json={"person_id_a": a, "person_id_b": b},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        # Vérifier que la paire est persistée (ids normalisés min/max
        # par le CHECK constraint).
        with _pool() as cur:
            cur.execute(
                "SELECT 1 FROM distinct_persons WHERE person_id_a = %s AND person_id_b = %s",
                (min(a, b), max(a, b)),
            )
            assert cur.fetchone() is not None


class TestPersonConflicts:
    def test_count_returns_total(self, client):
        r = client.get("/api/admin/person-duplicates/conflicts/count")
        assert r.status_code == 200
        assert "total" in r.json()

    def test_next_returns_pair_shape(self, client):
        r = client.get("/api/admin/person-duplicates/conflicts/next")
        assert r.status_code == 200
        assert "pair" in r.json()

    def test_next_accepts_skip_and_offset(self, client):
        r = client.get(
            "/api/admin/person-duplicates/conflicts/next",
            params={"skip": "10-20", "offset": 0},
        )
        assert r.status_code == 200
        assert "pair" in r.json()

    def test_next_negative_offset_rejected(self, client):
        r = client.get("/api/admin/person-duplicates/conflicts/next", params={"offset": -1})
        assert r.status_code == 422
