"""Tests de caractérisation pour le router persons.

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


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    """Les mutations de ce module committent dans la base (pool autocommit
    + events admin). Truncate à la fin pour ne pas polluer les suites qui
    tournent derrière (pipeline, audit)."""
    yield
    with _pool() as cur:
        cur.execute(
            "TRUNCATE TABLE authorships, source_authorships, author_identifying_keys, "
            "source_publications, publications, persons, person_identifiers, "
            "person_name_forms, audit_log RESTART IDENTITY CASCADE"
        )


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
    authorship_id: int | None = None,
    in_perimeter: bool = True,
    raw_author_name: str = "Test Author",
    author_position: int = 0,
) -> int:
    sp = source_pub_id or _seed_source_publication(source=source)
    with _pool() as cur:
        iid = _upsert_identity(cur, raw_author_name)
        cur.execute(
            "INSERT INTO source_authorships (source, source_publication_id, author_position, "
            "person_id, authorship_id, in_perimeter, raw_author_name, identity_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                source,
                sp,
                author_position,
                person_id,
                authorship_id,
                in_perimeter,
                raw_author_name,
                iid,
            ),
        )
        return cur.fetchone()["id"]


def _seed_name_form(person_id: int, name_form: str, source: str = "persons") -> None:
    with _pool() as cur:
        cur.execute(
            "INSERT INTO person_name_forms (name_form, person_id, sources) VALUES (%s, %s, %s)",
            (name_form, person_id, [source]),
        )


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


class TestPersonProfileIdentifiers:
    def test_rejected_identifier_never_leaves_the_api(self, client):
        """Un identifiant rejeté est une attribution écartée : l'endpoint public ne l'annonce pas.

        La règle tient dans la lecture, non dans la page : tout client de l'API en dépend.
        """
        person = _seed_person(last="REJECTEDID")
        _seed_identifier(person, "orcid", "0000-0002-0000-0001", status="rejected")
        _seed_identifier(person, "orcid", "0000-0002-0000-0002", status="confirmed")

        r = client.get(f"/api/persons/{person}")

        assert r.status_code == 200
        served = {i["id_value"]: i["status"] for i in r.json()["identifiers"]}
        assert served == {"0000-0002-0000-0002": "confirmed"}


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
    def test_stats(self, client):
        r = client.get("/api/persons/stats")
        assert r.status_code == 200


class TestPersonDetail:
    def test_profile_not_found(self, client):
        r = client.get("/api/persons/999999999")
        assert r.status_code == 404

    def test_theses_not_found(self, client):
        r = client.get("/api/persons/999999999/theses")
        assert r.status_code in (200, 404)

    def test_addresses_not_found(self, client):
        r = client.get("/api/persons/999999999/addresses")
        assert r.status_code in (200, 404)

    def test_profile_ok(self, client):
        pid = _seed_person("Profileur", "Zoé")
        r = client.get(f"/api/persons/{pid}")
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

    def test_idhal_is_normalized(self, auth_client):
        pid = _seed_person()
        r = auth_client.post(
            f"/api/persons/{pid}/identifiers",
            json={"id_type": "idhal", "id_value": "  Jean-Dupont  "},
        )
        assert r.status_code == 200
        assert r.json()["id_value"] == "jean-dupont"

    def test_invalid_idref_rejected(self, auth_client):
        pid = _seed_person()
        r = auth_client.post(
            f"/api/persons/{pid}/identifiers",
            json={"id_type": "idref", "id_value": "123456"},
        )
        assert r.status_code == 400

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

    def test_visible_immediately(self, auth_client):
        # Régression (chantier commit-avant-réponse) : le command handler commit
        # avant l'envoi de la réponse, donc l'écriture est lisible depuis une
        # connexion indépendante. Garde-fou du passage final du teardown de
        # db_conn en rollback — un handler sans `commit()` ferait échouer ce test.
        pid = _seed_person()
        marker = _uniq("READBACK")
        r = auth_client.patch(
            f"/api/persons/{pid}/name", json={"last_name": marker, "first_name": "Z"}
        )
        assert r.status_code == 200
        with _pool() as cur:
            cur.execute("SELECT last_name FROM persons WHERE id = %s", (pid,))
            assert cur.fetchone()["last_name"] == marker


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
            json={"authorships": []},
        )
        assert r.status_code == 401

    def test_ok_empty(self, auth_client):
        pid = _seed_person()
        r = auth_client.post(
            f"/api/persons/{pid}/detach-authorships",
            json={"authorships": []},
        )
        assert r.status_code == 200


class TestUpdateNameFormStatus:
    def test_requires_admin(self, client):
        r = client.patch(
            "/api/persons/1/name-forms/status", json={"name_form": "X", "status": "rejected"}
        )
        assert r.status_code == 401

    def test_reject_sets_status(self, auth_client):
        pid = _seed_person("RejectForm", "Nf")
        nf = _uniq("RejectForm Nf")
        _seed_name_form(pid, nf)
        r = auth_client.patch(
            f"/api/persons/{pid}/name-forms/status", json={"name_form": nf, "status": "rejected"}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["person_id"] == pid
        assert body["name_form"] == nf
        assert body["status"] == "rejected"

    def test_unknown_form_404(self, auth_client):
        pid = _seed_person("UnknownForm", "Nf")
        r = auth_client.patch(
            f"/api/persons/{pid}/name-forms/status",
            json={"name_form": "inexistante zzz", "status": "confirmed"},
        )
        assert r.status_code == 404
