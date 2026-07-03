"""Tests de caractérisation pour le router `admin/authorships`.

Couvre :
- PATCH /api/authorships/{id}/exclude
- GET / POST /api/admin/orphan-authorships/*

Stratégie : seed minimal via un pool dédié (hors pool API), ids uniques par
test pour éviter les collisions.
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


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _upsert_identity(cur, raw_author_name: str) -> int:
    """Upsert de l'identité (nom normalisé `lower(raw)`, sans identifiants) et
    renvoi de son id, sur le curseur psycopg du seed."""
    cur.execute(
        "INSERT INTO author_identifying_keys (author_name_normalized, person_identifiers) "
        "VALUES (lower(%s), NULL) ON CONFLICT DO NOTHING",
        (raw_author_name,),
    )
    cur.execute(
        "SELECT id FROM author_identifying_keys "
        "WHERE author_name_normalized IS NOT DISTINCT FROM lower(%s) AND person_identifiers IS NULL",
        (raw_author_name,),
    )
    return cur.fetchone()["id"]


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    """Truncate à la fin pour ne pas polluer les suites suivantes."""
    yield
    with _pool() as cur:
        cur.execute(
            "TRUNCATE TABLE authorships, source_authorships, author_identifying_keys, "
            "source_publications, publications, persons, audit_log RESTART IDENTITY CASCADE"
        )


def _seed_person(last: str = "TESTA", first: str = "J") -> int:
    with _pool() as cur:
        cur.execute(
            "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
            "VALUES (%s, %s, lower(%s), lower(%s)) RETURNING id",
            (last, first, last, first),
        )
        return cur.fetchone()["id"]


def _seed_publication(title: str = "T", year: int = 2024) -> int:
    with _pool() as cur:
        cur.execute(
            "INSERT INTO publications (title, title_normalized, pub_year) "
            "VALUES (%s, lower(%s), %s) RETURNING id",
            (title, title, year),
        )
        return cur.fetchone()["id"]


def _seed_authorship(publication_id: int, person_id: int | None = None) -> int:
    with _pool() as cur:
        cur.execute(
            "INSERT INTO authorships (publication_id, person_id, in_perimeter) "
            "VALUES (%s, %s, true) RETURNING id",
            (publication_id, person_id),
        )
        return cur.fetchone()["id"]


def _seed_source_publication(source: str = "hal", source_id: str | None = None) -> int:
    sid = source_id or _uniq("sid")
    with _pool() as cur:
        cur.execute(
            "INSERT INTO source_publications (source, source_id, title, pub_year) "
            "VALUES (%s, %s, 'T', 2024) RETURNING id",
            (source, sid),
        )
        return cur.fetchone()["id"]


def _seed_source_authorship(
    source: str = "hal",
    source_pub_id: int | None = None,
    person_id: int | None = None,
    raw_author_name: str = "Test Author",
) -> int:
    sp = source_pub_id or _seed_source_publication(source=source)
    with _pool() as cur:
        iid = _upsert_identity(cur, raw_author_name)
        cur.execute(
            "INSERT INTO source_authorships (source, source_publication_id, author_position, "
            "person_id, in_perimeter, raw_author_name, identity_id) "
            "VALUES (%s, %s, 0, %s, true, %s, %s) RETURNING id",
            (source, sp, person_id, raw_author_name, iid),
        )
        return cur.fetchone()["id"]


def _seed_orphan_authorship(raw_author_name: str) -> int:
    """source_authorship orpheline (person_id NULL, in_perimeter TRUE)."""
    pub_id = _seed_publication(title=_uniq("Pub"))
    with _pool() as cur:
        cur.execute(
            "INSERT INTO source_publications (source, source_id, title, pub_year, publication_id) "
            "VALUES ('hal', %s, 'T', 2024, %s) RETURNING id",
            (_uniq("sid"), pub_id),
        )
        sp_id = cur.fetchone()["id"]
    with _pool() as cur:
        iid = _upsert_identity(cur, raw_author_name)
        cur.execute(
            "INSERT INTO source_authorships (source, source_publication_id, author_position, "
            "person_id, in_perimeter, raw_author_name, identity_id) "
            "VALUES ('hal', %s, 0, NULL, TRUE, %s, %s) RETURNING id",
            (sp_id, raw_author_name, iid),
        )
        return cur.fetchone()["id"]


def _seed_orphan_with_pub(raw_author_name: str = "Reject Me") -> tuple[int, int]:
    """source_authorship orpheline rattachée à une publication.

    Renvoie (sa_id, publication_id) pour pouvoir rejeter la paire."""
    pub_id = _seed_publication(title=_uniq("Pub"))
    with _pool() as cur:
        cur.execute(
            "INSERT INTO source_publications (source, source_id, title, pub_year, publication_id) "
            "VALUES ('hal', %s, 'T', 2024, %s) RETURNING id",
            (_uniq("sid"), pub_id),
        )
        sp_id = cur.fetchone()["id"]
    sa_id = _seed_source_authorship(
        source="hal", source_pub_id=sp_id, raw_author_name=raw_author_name
    )
    return sa_id, pub_id


def _reject_pair(publication_id: int, person_id: int) -> None:
    with _pool() as cur:
        cur.execute(
            "INSERT INTO rejected_authorships (publication_id, person_id) VALUES (%s, %s)",
            (publication_id, person_id),
        )


# ── PATCH /api/authorships/{id}/exclude ─────────────────────────


class TestExcludeAuthorship:
    def test_requires_admin(self, client):
        r = client.patch("/api/authorships/1/exclude")
        assert r.status_code == 401

    def test_ok(self, auth_client):
        pid = _seed_person()
        pub = _seed_publication("Exclude test")
        aid = _seed_authorship(pub, person_id=pid)
        r = auth_client.patch(f"/api/authorships/{aid}/exclude")
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ── Orphan authorships ──────────────────────────────────────────


class TestOrphanAuthorships:
    def test_count(self, client):
        r = client.get("/api/admin/orphan-authorships/count")
        assert r.status_code == 200

    def test_list(self, client):
        r = client.get("/api/admin/orphan-authorships", params={"page": 1, "per_page": 50})
        assert r.status_code == 200

    def test_list_with_search(self, client):
        r = client.get("/api/admin/orphan-authorships", params={"search": "foo"})
        assert r.status_code == 200

    def test_returns_last_name_first_name_from_comma_form(self, client):
        """Format "Last, First" : parsé en last_name="Last", first_name="First"."""
        marker = _uniq("Marker").replace("_", "")
        _seed_orphan_authorship(f"{marker}, Jane")

        r = client.get("/api/admin/orphan-authorships", params={"search": marker})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        item = body["authorships"][0]
        assert item["last_name"] == marker
        assert item["first_name"] == "Jane"
        assert item["full_name"] == f"{marker}, Jane"

    def test_returns_last_name_first_name_from_space_form(self, client):
        """Format "First Last" : parsé en last_name=dernier mot, first_name=reste."""
        marker = _uniq("Marker").replace("_", "")
        _seed_orphan_authorship(f"Jane Marie {marker}")

        r = client.get("/api/admin/orphan-authorships", params={"search": marker})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        item = body["authorships"][0]
        assert item["last_name"] == marker
        assert item["first_name"] == "Jane Marie"


class TestAssignOrphanAuthorship:
    def test_requires_admin(self, client):
        r = client.post(
            "/api/admin/orphan-authorships/assign",
            json={"source": "hal", "authorship_id": 1, "person_id": 1},
        )
        assert r.status_code == 401

    def test_unknown_source(self, auth_client):
        r = auth_client.post(
            "/api/admin/orphan-authorships/assign",
            json={"source": "unknown_source", "authorship_id": 1, "person_id": 1},
        )
        assert r.status_code == 400

    def test_missing_person_id_and_create(self, auth_client):
        sa = _seed_source_authorship(source="hal")
        r = auth_client.post(
            "/api/admin/orphan-authorships/assign",
            json={"source": "hal", "authorship_id": sa},
        )
        assert r.status_code == 400

    def test_create_person_empty_name(self, auth_client):
        sa = _seed_source_authorship(source="hal")
        r = auth_client.post(
            "/api/admin/orphan-authorships/assign",
            json={
                "source": "hal",
                "authorship_id": sa,
                "create_person": {"last_name": "   ", "first_name": "X"},
            },
        )
        assert r.status_code == 400

    def test_person_not_found(self, auth_client):
        sa = _seed_source_authorship(source="hal")
        r = auth_client.post(
            "/api/admin/orphan-authorships/assign",
            json={"source": "hal", "authorship_id": sa, "person_id": 999999999},
        )
        assert r.status_code == 404

    def test_ok_with_person_id(self, auth_client):
        pid = _seed_person()
        sa = _seed_source_authorship(source="hal")
        r = auth_client.post(
            "/api/admin/orphan-authorships/assign",
            json={"source": "hal", "authorship_id": sa, "person_id": pid},
        )
        assert r.status_code == 200
        assert r.json()["person_id"] == pid

    def test_assign_visible_immediately(self, auth_client):
        # Régression (chantier commit-avant-réponse) : le command handler commit
        # avant l'envoi de la réponse, donc le rattachement est lisible depuis une
        # connexion indépendante. Garde-fou du passage final du teardown de
        # db_conn_sync en rollback — un handler sans `commit()` ferait échouer ce test.
        pid = _seed_person()
        sa = _seed_source_authorship(source="hal")
        r = auth_client.post(
            "/api/admin/orphan-authorships/assign",
            json={"source": "hal", "authorship_id": sa, "person_id": pid},
        )
        assert r.status_code == 200
        with _pool() as cur:
            cur.execute("SELECT person_id FROM source_authorships WHERE id = %s", (sa,))
            assert cur.fetchone()["person_id"] == pid

    def test_ok_with_create_person(self, auth_client):
        sa = _seed_source_authorship(source="hal")
        r = auth_client.post(
            "/api/admin/orphan-authorships/assign",
            json={
                "source": "hal",
                "authorship_id": sa,
                "create_person": {"last_name": "Créée", "first_name": "Ici"},
            },
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_blocked_when_pair_rejected(self, auth_client):
        pid = _seed_person()
        sa, pub = _seed_orphan_with_pub()
        _reject_pair(pub, pid)
        r = auth_client.post(
            "/api/admin/orphan-authorships/assign",
            json={"source": "hal", "authorship_id": sa, "person_id": pid},
        )
        assert r.status_code == 409
        pair = r.json()["rejected_pairs"][0]
        assert pair["publication_id"] == pub
        assert pair["person_id"] == pid
        assert pair["rejected_at"]

    def test_forced_unrejects_and_assigns(self, auth_client):
        pid = _seed_person()
        sa, pub = _seed_orphan_with_pub()
        _reject_pair(pub, pid)
        r = auth_client.post(
            "/api/admin/orphan-authorships/assign",
            json={"source": "hal", "authorship_id": sa, "person_id": pid, "force": True},
        )
        assert r.status_code == 200
        assert r.json()["person_id"] == pid


class TestBatchAssignOrphanAuthorships:
    def test_requires_admin(self, client):
        r = client.post(
            "/api/admin/orphan-authorships/batch-assign",
            json={"authorships": [], "person_id": 1},
        )
        assert r.status_code == 401

    def test_empty_authorships_ok_zero(self, auth_client):
        pid = _seed_person()
        r = auth_client.post(
            "/api/admin/orphan-authorships/batch-assign",
            json={"authorships": [], "person_id": pid},
        )
        assert r.status_code == 200
        assert r.json()["assigned"] == 0

    def test_all_sources_unknown_returns_zero(self, auth_client):
        pid = _seed_person()
        r = auth_client.post(
            "/api/admin/orphan-authorships/batch-assign",
            json={
                "authorships": [{"source": "unknown", "authorship_id": 1}],
                "person_id": pid,
            },
        )
        assert r.status_code == 200
        assert r.json()["assigned"] == 0

    def test_person_not_found(self, auth_client):
        sa = _seed_source_authorship(source="hal")
        r = auth_client.post(
            "/api/admin/orphan-authorships/batch-assign",
            json={
                "authorships": [{"source": "hal", "authorship_id": sa}],
                "person_id": 999999999,
            },
        )
        assert r.status_code == 404

    def test_ok(self, auth_client):
        pid = _seed_person()
        sa1 = _seed_source_authorship(source="hal")
        sa2 = _seed_source_authorship(source="openalex")
        r = auth_client.post(
            "/api/admin/orphan-authorships/batch-assign",
            json={
                "authorships": [
                    {"source": "hal", "authorship_id": sa1},
                    {"source": "openalex", "authorship_id": sa2},
                ],
                "person_id": pid,
            },
        )
        assert r.status_code == 200
        assert r.json()["assigned"] >= 0

    def test_blocked_when_pair_rejected(self, auth_client):
        pid = _seed_person()
        sa, pub = _seed_orphan_with_pub()
        _reject_pair(pub, pid)
        r = auth_client.post(
            "/api/admin/orphan-authorships/batch-assign",
            json={"authorships": [{"source": "hal", "authorship_id": sa}], "person_id": pid},
        )
        assert r.status_code == 409
        assert r.json()["rejected_pairs"][0]["publication_id"] == pub

    def test_forced_unrejects_and_assigns(self, auth_client):
        pid = _seed_person()
        sa, pub = _seed_orphan_with_pub()
        _reject_pair(pub, pid)
        r = auth_client.post(
            "/api/admin/orphan-authorships/batch-assign",
            json={
                "authorships": [{"source": "hal", "authorship_id": sa}],
                "person_id": pid,
                "force": True,
            },
        )
        assert r.status_code == 200
        assert r.json()["assigned"] == 1
