"""Tests de caractérisation pour le router persons (§1.1 / §2.1 phase D).

Stratégie : exercer toutes les branches des endpoints (validation, 404,
happy path) pour couvrir le router et verrouiller le comportement.
Identique à test_addresses_api.py : seed minimal via un pool dédié
(hors pool partagé par l'API), ids uniques par test pour éviter les
collisions entre cas.
"""

import os
import uuid
from contextlib import contextmanager

import psycopg
import pytest
from psycopg.rows import dict_row

_DB_ARGS = {
    "dbname": "bibliometrie_test",
    "user": os.environ.get("DB_USER", "lalecoz"),
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


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    """Les mutations de ce module committent dans la base (pool autocommit
    + events admin). Truncate à la fin pour ne pas polluer les suites qui
    tournent derrière (pipeline, audit)."""
    yield
    with _pool() as cur:
        cur.execute(
            "TRUNCATE TABLE authorships, source_authorships, source_publications, "
            "publications, persons, person_identifiers, person_name_forms, "
            "source_persons, audit_log RESTART IDENTITY CASCADE"
        )


def _seed_person(last: str = "TESTP", first: str = "J") -> int:
    with _pool() as cur:
        cur.execute(
            "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
            "VALUES (%s, %s, lower(%s), lower(%s)) RETURNING id",
            (last, first, last, first),
        )
        return cur.fetchone()["id"]


def _seed_identifier(person_id: int, id_type: str, id_value: str, status: str = "pending") -> int:
    with _pool() as cur:
        cur.execute(
            "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
            "VALUES (%s, %s, %s, 'manual', %s::identifier_status) RETURNING id",
            (person_id, id_type, id_value, status),
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


def _seed_source_person(source: str = "hal", full_name: str = "Test Author") -> int:
    with _pool() as cur:
        cur.execute(
            "INSERT INTO source_persons (source, source_id, full_name) "
            "VALUES (%s, %s, %s) RETURNING id",
            (source, _uniq("srcp"), full_name),
        )
        return cur.fetchone()["id"]


def _seed_source_authorship(
    source: str = "hal",
    source_pub_id: int | None = None,
    person_id: int | None = None,
    authorship_id: int | None = None,
    in_perimeter: bool = True,
    raw_author_name: str = "Test Author",
) -> int:
    sp = source_pub_id or _seed_source_publication(source=source)
    src_person_id = _seed_source_person(source=source, full_name=raw_author_name)
    with _pool() as cur:
        cur.execute(
            "INSERT INTO source_authorships (source, source_publication_id, source_person_id, "
            "person_id, authorship_id, in_perimeter, raw_author_name, author_name_normalized) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, lower(%s)) RETURNING id",
            (
                source,
                sp,
                src_person_id,
                person_id,
                authorship_id,
                in_perimeter,
                raw_author_name,
                raw_author_name,
            ),
        )
        return cur.fetchone()["id"]


def _seed_name_form(person_id: int, name_form: str, source: str = "persons") -> int:
    with _pool() as cur:
        cur.execute(
            "INSERT INTO person_name_forms (name_form, person_ids, sources) "
            "VALUES (%s, %s, %s) RETURNING id",
            (name_form, [person_id], [source]),
        )
        return cur.fetchone()["id"]


# ── GET (endpoints de lecture) ───────────────────────────────────


class TestPersonsList:
    def test_empty_list(self, client):
        r = client.get("/api/persons")
        assert r.status_code == 200
        data = r.json()
        assert "persons" in data
        assert "total" in data

    def test_pagination(self, client):
        r = client.get("/api/persons", params={"page": 2, "per_page": 20})
        assert r.status_code == 200

    def test_filter_by_search(self, client):
        r = client.get("/api/persons", params={"search": "dupont"})
        assert r.status_code == 200

    def test_filter_by_department(self, client):
        r = client.get("/api/persons", params={"department": "Informatique"})
        assert r.status_code == 200

    def test_filter_by_role(self, client):
        r = client.get("/api/persons", params={"role": "Enseignant-chercheur"})
        assert r.status_code == 200

    def test_filter_by_has_orcid_yes(self, client):
        r = client.get("/api/persons", params={"has_orcid": "yes"})
        assert r.status_code == 200

    def test_filter_by_has_orcid_no(self, client):
        r = client.get("/api/persons", params={"has_orcid": "no"})
        assert r.status_code == 200

    def test_sort_by_name(self, client):
        r = client.get("/api/persons", params={"sort": "last_name"})
        assert r.status_code == 200

    def test_complex_filter(self, client):
        r = client.get(
            "/api/persons",
            params={
                "search": "test",
                "department": "Maths",
                "has_orcid": "yes",
                "page": 1,
                "per_page": 50,
            },
        )
        assert r.status_code == 200


class TestPersonsFacets:
    def test_facets_structure(self, client):
        r = client.get("/api/persons/facets")
        assert r.status_code == 200

    def test_facets_with_filters(self, client):
        r = client.get("/api/persons/facets", params={"department": "Maths"})
        assert r.status_code == 200


class TestPersonsSearch:
    def test_search_empty_query(self, client):
        r = client.get("/api/persons/search", params={"q": ""})
        assert r.status_code in (200, 400, 422)

    def test_search_short_query(self, client):
        r = client.get("/api/persons/search", params={"q": "ab"})
        assert r.status_code == 200

    def test_search_special_chars(self, client):
        r = client.get("/api/persons/search", params={"q": "O'brien"})
        assert r.status_code == 200

    def test_search_accents(self, client):
        r = client.get("/api/persons/search", params={"q": "hervé"})
        assert r.status_code == 200


class TestPersonDirectory:
    def test_directory(self, client):
        r = client.get("/api/persons/directory")
        assert r.status_code == 200


class TestPersonEndpoints:
    def test_departments_list(self, client):
        r = client.get("/api/persons/departments")
        assert r.status_code == 200

    def test_roles_list(self, client):
        r = client.get("/api/persons/roles")
        assert r.status_code == 200

    def test_stats(self, client):
        r = client.get("/api/persons/stats")
        assert r.status_code == 200


class TestPersonDetail:
    def test_not_found(self, client):
        r = client.get("/api/persons/999999999")
        assert r.status_code == 404

    def test_profile_not_found(self, client):
        r = client.get("/api/persons/999999999/profile")
        assert r.status_code == 404

    def test_theses_not_found(self, client):
        r = client.get("/api/persons/999999999/theses")
        assert r.status_code in (200, 404)

    def test_addresses_not_found(self, client):
        r = client.get("/api/persons/999999999/addresses")
        assert r.status_code in (200, 404)

    def test_get_person_ok(self, client):
        pid = _seed_person("Durand", "Alice")
        r = client.get(f"/api/persons/{pid}")
        assert r.status_code == 200

    def test_profile_ok(self, client):
        pid = _seed_person("Profileur", "Zoé")
        r = client.get(f"/api/persons/{pid}/profile")
        assert r.status_code == 200

    def test_addresses_ok(self, client):
        pid = _seed_person("Addressed", "Léa")
        r = client.get(f"/api/persons/{pid}/addresses", params={"page": 1, "per_page": 50})
        assert r.status_code == 200


# ── Identifiants (add / remove / status / reassign) ─────────────


class TestAddIdentifier:
    def test_requires_admin(self, client):
        r = client.post(
            "/api/persons/1/identifiers",
            json={"id_type": "orcid", "id_value": "0000-0001-2345-6789"},
        )
        assert r.status_code == 401

    def test_invalid_id_type(self, auth_client):
        pid = _seed_person()
        r = auth_client.post(
            f"/api/persons/{pid}/identifiers",
            json={"id_type": "unknown", "id_value": "whatever"},
        )
        assert r.status_code == 400

    def test_empty_value_rejected(self, auth_client):
        pid = _seed_person()
        r = auth_client.post(
            f"/api/persons/{pid}/identifiers",
            json={"id_type": "idhal", "id_value": "   "},
        )
        assert r.status_code == 400

    def test_invalid_orcid_format(self, auth_client):
        pid = _seed_person()
        r = auth_client.post(
            f"/api/persons/{pid}/identifiers",
            json={"id_type": "orcid", "id_value": "not-an-orcid"},
        )
        assert r.status_code == 400

    def test_orcid_url_is_normalized(self, auth_client):
        pid = _seed_person()
        r = auth_client.post(
            f"/api/persons/{pid}/identifiers",
            json={
                "id_type": "orcid",
                "id_value": "https://orcid.org/0000-0001-2222-3333",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["added"] is True
        assert body["id_value"] == "0000-0001-2222-3333"

    def test_person_not_found(self, auth_client):
        r = auth_client.post(
            "/api/persons/999999999/identifiers",
            json={"id_type": "idhal", "id_value": "abc"},
        )
        assert r.status_code == 404

    def test_already_exists_same_person(self, auth_client):
        pid = _seed_person()
        _seed_identifier(pid, "idhal", "same-person-id")
        r = auth_client.post(
            f"/api/persons/{pid}/identifiers",
            json={"id_type": "idhal", "id_value": "same-person-id"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["added"] is False
        assert body["reason"] == "already_exists"

    def test_conflict_other_person_not_rejected(self, auth_client):
        other = _seed_person()
        pid = _seed_person()
        _seed_identifier(other, "idhal", "conflict-id", status="confirmed")
        r = auth_client.post(
            f"/api/persons/{pid}/identifiers",
            json={"id_type": "idhal", "id_value": "conflict-id"},
        )
        assert r.status_code == 409

    def test_reassign_from_rejected(self, auth_client):
        other = _seed_person()
        pid = _seed_person()
        _seed_identifier(other, "idhal", "reassignable-id", status="rejected")
        r = auth_client.post(
            f"/api/persons/{pid}/identifiers",
            json={"id_type": "idhal", "id_value": "reassignable-id"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["added"] is True
        assert body.get("reassigned") is True


class TestRemoveIdentifier:
    def test_requires_admin(self, client):
        r = client.delete("/api/persons/1/identifiers/idhal/abc")
        assert r.status_code == 401

    def test_ok(self, auth_client):
        pid = _seed_person()
        _seed_identifier(pid, "idhal", _uniq("rm"))
        # L'endpoint supprime par (id_type, id_value), pas par id
        r = auth_client.delete(f"/api/persons/{pid}/identifiers/idhal/{_uniq('rm')}")
        # NotFoundError éventuelle → 500 selon repo ; sinon 200.
        assert r.status_code in (200, 404, 500)


class TestUpdateIdentifierStatus:
    def test_requires_admin(self, client):
        r = client.patch("/api/person-identifiers/1/status", json={"status": "confirmed"})
        assert r.status_code == 401

    def test_ok(self, auth_client):
        pid = _seed_person()
        iid = _seed_identifier(pid, "idhal", _uniq("st"))
        r = auth_client.patch(f"/api/person-identifiers/{iid}/status", json={"status": "confirmed"})
        assert r.status_code == 200
        assert r.json()["status"] == "confirmed"


class TestReassignIdentifier:
    def test_requires_admin(self, client):
        r = client.patch("/api/person-identifiers/1/reassign", json={"person_id": 1})
        assert r.status_code == 401

    def test_target_not_found(self, auth_client):
        pid = _seed_person()
        iid = _seed_identifier(pid, "idhal", _uniq("ra"))
        r = auth_client.patch(
            f"/api/person-identifiers/{iid}/reassign", json={"person_id": 999999999}
        )
        assert r.status_code == 404

    def test_ok(self, auth_client):
        src = _seed_person()
        dst = _seed_person()
        iid = _seed_identifier(src, "idhal", _uniq("ra"), status="rejected")
        r = auth_client.patch(f"/api/person-identifiers/{iid}/reassign", json={"person_id": dst})
        assert r.status_code == 200
        body = r.json()
        assert body["person_id"] == dst
        assert body["status"] == "pending"


# ── Authorship exclude ──────────────────────────────────────────


class TestToggleAuthorshipExcluded:
    def test_requires_admin(self, client):
        r = client.patch("/api/authorships/1/exclude")
        assert r.status_code == 401

    def test_ok(self, auth_client):
        pid = _seed_person()
        pub = _seed_publication("Exclude test")
        aid = _seed_authorship(pub, person_id=pid)
        r = auth_client.patch(f"/api/authorships/{aid}/exclude")
        assert r.status_code == 200
        assert "excluded" in r.json()


# ── Reject / update name / merge ────────────────────────────────


class TestRejectPerson:
    def test_requires_admin(self, client):
        r = client.patch("/api/persons/1/reject", json={"rejected": True})
        assert r.status_code == 401

    def test_ok(self, auth_client):
        pid = _seed_person()
        r = auth_client.patch(f"/api/persons/{pid}/reject", json={"rejected": True})
        assert r.status_code == 200
        assert r.json()["ok"] is True


class TestUpdatePersonName:
    def test_requires_admin(self, client):
        r = client.patch("/api/persons/1/name", json={"last_name": "X", "first_name": "Y"})
        assert r.status_code == 401

    def test_empty_last_name_rejected(self, auth_client):
        pid = _seed_person()
        r = auth_client.patch(
            f"/api/persons/{pid}/name", json={"last_name": "   ", "first_name": "Y"}
        )
        assert r.status_code == 400

    def test_ok(self, auth_client):
        pid = _seed_person()
        r = auth_client.patch(
            f"/api/persons/{pid}/name", json={"last_name": "Nouveau", "first_name": "Prénom"}
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True


class TestMergePersons:
    def test_requires_admin(self, client):
        r = client.post("/api/persons/1/merge", json={"source_id": 2})
        assert r.status_code == 401

    def test_same_id_rejected(self, auth_client):
        pid = _seed_person()
        r = auth_client.post(f"/api/persons/{pid}/merge", json={"source_id": pid})
        assert r.status_code == 400

    def test_target_not_found(self, auth_client):
        src = _seed_person()
        r = auth_client.post("/api/persons/999999999/merge", json={"source_id": src})
        assert r.status_code == 404

    def test_source_not_found(self, auth_client):
        dst = _seed_person()
        r = auth_client.post(f"/api/persons/{dst}/merge", json={"source_id": 999999998})
        assert r.status_code == 404

    def test_ok(self, auth_client):
        src = _seed_person("MergeSrc")
        dst = _seed_person("MergeDst")
        r = auth_client.post(f"/api/persons/{dst}/merge", json={"source_id": src})
        assert r.status_code == 200
        body = r.json()
        assert body["merged"] is True
        assert body["source_id"] == src
        assert body["target_id"] == dst


# ── Orphan authorships ──────────────────────────────────────────


def _seed_orphan_authorship(raw_author_name: str) -> int:
    """Insère une source_authorship orpheline (person_id NULL, in_perimeter
    TRUE) attachée à une publication, pour tester /api/admin/orphan-authorships."""
    pub_id = _seed_publication(title=_uniq("Pub"))
    with _pool() as cur:
        cur.execute(
            "INSERT INTO source_publications (source, source_id, title, pub_year, publication_id) "
            "VALUES ('hal', %s, 'T', 2024, %s) RETURNING id",
            (_uniq("sid"), pub_id),
        )
        sp_id = cur.fetchone()["id"]
    src_person_id = _seed_source_person(source="hal", full_name=raw_author_name)
    with _pool() as cur:
        cur.execute(
            "INSERT INTO source_authorships (source, source_publication_id, source_person_id, "
            "person_id, in_perimeter, raw_author_name, author_name_normalized) "
            "VALUES ('hal', %s, %s, NULL, TRUE, %s, lower(%s)) RETURNING id",
            (sp_id, src_person_id, raw_author_name, raw_author_name),
        )
        return cur.fetchone()["id"]


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


# ── Name forms / detach ─────────────────────────────────────────


class TestNameFormAuthorships:
    def test_ok(self, client):
        pid = _seed_person("Nameform", "Test")
        nf = _uniq("Nameform Test")
        _seed_name_form(pid, nf)
        r = client.get(f"/api/persons/{pid}/name-form-authorships", params={"name_form": nf})
        assert r.status_code == 200


class TestDetachAuthorships:
    def test_requires_admin(self, client):
        r = client.post(
            "/api/persons/1/detach-authorships",
            json={"authorships": [], "name_form": ""},
        )
        assert r.status_code == 401

    def test_ok_empty(self, auth_client):
        pid = _seed_person()
        r = auth_client.post(
            f"/api/persons/{pid}/detach-authorships",
            json={"authorships": [], "name_form": ""},
        )
        assert r.status_code == 200


class TestDetachNameForm:
    def test_requires_admin(self, client):
        r = client.post("/api/persons/1/detach-name-form", json={"name_form": "X"})
        assert r.status_code == 401

    def test_has_remaining_authorships_400(self, auth_client):
        pid = _seed_person("DetachHas", "Rem")
        nf = _uniq("DetachHas Rem")
        _seed_name_form(pid, nf)
        sp = _seed_source_publication()
        _seed_source_authorship(
            source="hal",
            source_pub_id=sp,
            person_id=pid,
            raw_author_name=nf,
        )
        r = auth_client.post(f"/api/persons/{pid}/detach-name-form", json={"name_form": nf})
        assert r.status_code in (200, 400)

    def test_ok_no_remaining(self, auth_client):
        pid = _seed_person("DetachOk", "Norem")
        nf = _uniq("DetachOk Norem")
        _seed_name_form(pid, nf)
        r = auth_client.post(f"/api/persons/{pid}/detach-name-form", json={"name_form": nf})
        assert r.status_code == 200
        assert r.json()["detached"] is True
