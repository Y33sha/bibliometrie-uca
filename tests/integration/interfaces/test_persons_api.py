"""Tests de caractérisation pour le router persons.

Stratégie : exercer toutes les branches des endpoints (validation, 404,
happy path) pour couvrir le router et verrouiller le comportement.
Identique à test_addresses_api.py : seed minimal via un pool dédié
(hors pool partagé par l'API), ids uniques par test pour éviter les
collisions entre cas.
"""

import pytest

from tests.integration.helpers.db import owner_pool
from tests.integration.helpers.seeds import (
    seed_person,
    uniq,
)


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    """Les mutations de ce module committent dans la base (pool autocommit
    + events admin). Truncate à la fin pour ne pas polluer les suites qui
    tournent derrière (pipeline, audit)."""
    yield
    with owner_pool() as cur:
        cur.execute(
            "TRUNCATE TABLE authorships, source_authorships, author_identifying_keys, "
            "source_publications, publications, persons, person_identifiers, "
            "person_name_forms, audit_log RESTART IDENTITY CASCADE"
        )


def _seed_identifier(person_id: int, id_type: str, id_value: str, status: str = "pending") -> int:
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
            "VALUES (%s, %s, %s, 'manual', %s::identifier_status) RETURNING id",
            (person_id, id_type, id_value, status),
        )
        return cur.fetchone()["id"]


def _seed_name_form(person_id: int, name_form: str, source: str = "persons") -> None:
    with owner_pool() as cur:
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
        r = client.get("/api/persons", params={"sort": "name_desc"})
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
        person = seed_person(last="REJECTEDID")
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
        r = client.get("/api/persons/search", params={"search": ""})
        assert r.status_code in (200, 422)

    def test_search_short_query(self, client):
        r = client.get("/api/persons/search", params={"search": "ab"})
        assert r.status_code == 200

    def test_search_special_chars(self, client):
        r = client.get("/api/persons/search", params={"search": "O'brien"})
        assert r.status_code == 200

    def test_search_accents(self, client):
        r = client.get("/api/persons/search", params={"search": "hervé"})
        assert r.status_code == 200


class TestPersonList:
    def test_list(self, client):
        r = client.get("/api/persons")
        assert r.status_code == 200

    def test_public_directory_call(self, client):
        """L'appel de l'annuaire public : personnes retenues, tri sur les signatures d'auteur."""
        r = client.get(
            "/api/persons", params={"exclusion": "none", "sort": "signatures_as_author_desc"}
        )
        assert r.status_code == 200
        assert all(p["exclusion"] is None for p in r.json()["persons"])

    def test_unknown_exclusion_is_422(self, client):
        r = client.get("/api/persons", params={"exclusion": "none,autre"})
        assert r.status_code == 422

    def test_unknown_sort_rejected(self, client):
        r = client.get("/api/persons", params={"sort": "pub_count_desc"})
        assert r.status_code == 422


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
        pid = seed_person("Profileur", "Zoé")
        r = client.get(f"/api/persons/{pid}")
        assert r.status_code == 200

    def test_addresses_ok(self, client):
        pid = seed_person("Addressed", "Léa")
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
        # Valeur hors de l'énum `PersonIdentifierType` : rejetée au bord par Pydantic (422).
        pid = seed_person()
        r = auth_client.post(
            f"/api/persons/{pid}/identifiers",
            json={"id_type": "unknown", "id_value": "whatever"},
        )
        assert r.status_code == 422

    def test_empty_value_rejected(self, auth_client):
        pid = seed_person()
        r = auth_client.post(
            f"/api/persons/{pid}/identifiers",
            json={"id_type": "idhal", "id_value": "   "},
        )
        assert r.status_code == 422

    def test_invalid_orcid_format(self, auth_client):
        pid = seed_person()
        r = auth_client.post(
            f"/api/persons/{pid}/identifiers",
            json={"id_type": "orcid", "id_value": "not-an-orcid"},
        )
        assert r.status_code == 422

    def test_orcid_url_is_normalized(self, auth_client):
        pid = seed_person()
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
        pid = seed_person()
        r = auth_client.post(
            f"/api/persons/{pid}/identifiers",
            json={"id_type": "idhal", "id_value": "  Jean-Dupont  "},
        )
        assert r.status_code == 200
        assert r.json()["id_value"] == "jean-dupont"

    def test_invalid_idref_rejected(self, auth_client):
        pid = seed_person()
        r = auth_client.post(
            f"/api/persons/{pid}/identifiers",
            json={"id_type": "idref", "id_value": "123456"},
        )
        assert r.status_code == 422

    def test_person_not_found(self, auth_client):
        r = auth_client.post(
            "/api/persons/999999999/identifiers",
            json={"id_type": "idhal", "id_value": "abc"},
        )
        assert r.status_code == 404

    def test_already_exists_same_person(self, auth_client):
        pid = seed_person()
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
        other = seed_person()
        pid = seed_person()
        _seed_identifier(other, "idhal", "conflict-id", status="confirmed")
        r = auth_client.post(
            f"/api/persons/{pid}/identifiers",
            json={"id_type": "idhal", "id_value": "conflict-id"},
        )
        assert r.status_code == 409

    def test_reassign_from_rejected(self, auth_client):
        other = seed_person()
        pid = seed_person()
        _seed_identifier(other, "idhal", "reassignable-id", status="rejected")
        r = auth_client.post(
            f"/api/persons/{pid}/identifiers",
            json={"id_type": "idhal", "id_value": "reassignable-id"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["added"] is True
        assert body.get("reassigned") is True


class TestUpdateIdentifierStatus:
    def test_requires_admin(self, client):
        r = client.patch("/api/persons/identifiers/1/status", json={"status": "confirmed"})
        assert r.status_code == 401

    def test_ok(self, auth_client):
        pid = seed_person()
        iid = _seed_identifier(pid, "idhal", uniq("st"))
        r = auth_client.patch(
            f"/api/persons/identifiers/{iid}/status", json={"status": "confirmed"}
        )
        assert r.status_code == 200
        assert r.json()["status"] == "confirmed"


class TestReassignIdentifier:
    def test_requires_admin(self, client):
        r = client.patch("/api/persons/identifiers/1/reassign", json={"person_id": 1})
        assert r.status_code == 401

    def test_target_not_found(self, auth_client):
        pid = seed_person()
        iid = _seed_identifier(pid, "idhal", uniq("ra"))
        r = auth_client.patch(
            f"/api/persons/identifiers/{iid}/reassign", json={"person_id": 999999999}
        )
        assert r.status_code == 404

    def test_ok(self, auth_client):
        src = seed_person()
        dst = seed_person()
        iid = _seed_identifier(src, "idhal", uniq("ra"), status="rejected")
        r = auth_client.patch(f"/api/persons/identifiers/{iid}/reassign", json={"person_id": dst})
        assert r.status_code == 200
        body = r.json()
        assert body["person_id"] == dst
        assert body["status"] == "pending"


# ── Reject / update name / merge ────────────────────────────────


class TestSetPersonExclusion:
    def test_requires_admin(self, client):
        r = client.patch("/api/persons/1/exclusion", json={"exclusion": "not_a_person"})
        assert r.status_code == 401

    def test_ok(self, auth_client):
        pid = seed_person()
        r = auth_client.patch(
            f"/api/persons/{pid}/exclusion", json={"exclusion": "out_of_perimeter"}
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_unknown_reason_is_422(self, auth_client):
        pid = seed_person()
        r = auth_client.patch(f"/api/persons/{pid}/exclusion", json={"exclusion": "autre"})
        assert r.status_code == 422


class TestUpdatePersonName:
    def test_requires_admin(self, client):
        r = client.patch("/api/persons/1/name", json={"last_name": "X", "first_name": "Y"})
        assert r.status_code == 401

    def test_empty_last_name_rejected(self, auth_client):
        pid = seed_person()
        r = auth_client.patch(
            f"/api/persons/{pid}/name", json={"last_name": "   ", "first_name": "Y"}
        )
        assert r.status_code == 422

    def test_ok(self, auth_client):
        pid = seed_person()
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
        pid = seed_person()
        marker = uniq("READBACK")
        r = auth_client.patch(
            f"/api/persons/{pid}/name", json={"last_name": marker, "first_name": "Z"}
        )
        assert r.status_code == 200
        with owner_pool() as cur:
            cur.execute("SELECT last_name FROM persons WHERE id = %s", (pid,))
            assert cur.fetchone()["last_name"] == marker


class TestMergePersons:
    def test_requires_admin(self, client):
        r = client.post("/api/persons/1/merge", json={"source_id": 2})
        assert r.status_code == 401

    def test_same_id_rejected(self, auth_client):
        pid = seed_person()
        r = auth_client.post(f"/api/persons/{pid}/merge", json={"source_id": pid})
        assert r.status_code == 422

    def test_target_not_found(self, auth_client):
        src = seed_person()
        r = auth_client.post("/api/persons/999999999/merge", json={"source_id": src})
        assert r.status_code == 404

    def test_source_not_found(self, auth_client):
        dst = seed_person()
        r = auth_client.post(f"/api/persons/{dst}/merge", json={"source_id": 999999998})
        assert r.status_code == 404

    def test_ok(self, auth_client):
        src = seed_person("MergeSrc")
        dst = seed_person("MergeDst")
        r = auth_client.post(f"/api/persons/{dst}/merge", json={"source_id": src})
        assert r.status_code == 200
        body = r.json()
        assert body["merged"] is True
        assert body["source_id"] == src
        assert body["target_id"] == dst


# ── Name forms / detach ─────────────────────────────────────────


class TestNameFormAuthorships:
    def test_ok(self, client):
        pid = seed_person("Nameform", "Test")
        nf = uniq("Nameform Test")
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
        pid = seed_person()
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
        pid = seed_person("RejectForm", "Nf")
        nf = uniq("RejectForm Nf")
        _seed_name_form(pid, nf, source="hal")
        r = auth_client.patch(
            f"/api/persons/{pid}/name-forms/status", json={"name_form": nf, "status": "rejected"}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["person_id"] == pid
        assert body["name_form"] == nf
        assert body["status"] == "rejected"

    def test_unknown_form_404(self, auth_client):
        pid = seed_person("UnknownForm", "Nf")
        r = auth_client.patch(
            f"/api/persons/{pid}/name-forms/status",
            json={"name_form": "inexistante zzz", "status": "confirmed"},
        )
        assert r.status_code == 404


class TestPersonDashboardAndSubjects:
    def test_dashboard_of_unknown_person(self, client):
        """Le tableau de bord d'un id inconnu rend une réponse vide, non un 404."""
        r = client.get("/api/persons/999999999/dashboard")
        assert r.status_code == 200

    def test_dashboard_of_seeded_person(self, client):
        pid = seed_person("Dash", "Bo")
        r = client.get(f"/api/persons/{pid}/dashboard")
        assert r.status_code == 200

    def test_subjects_of_person_without_publication(self, client):
        pid = seed_person("Subj", "Ec")
        r = client.get(f"/api/persons/{pid}/subjects")
        assert r.status_code == 200
        assert r.json() == []

    def test_subjects_honours_limit(self, client):
        pid = seed_person("SubjLim", "Ec")
        r = client.get(f"/api/persons/{pid}/subjects", params={"limit": 5})
        assert r.status_code == 200


class TestTriageQueues:
    """Les files de triage et leurs compteurs, exercées sur une base sans cas à trancher."""

    QUEUES = (
        "ambiguous-name-forms",
        "identifier-conflicts",
        "name-duplicates",
    )

    @pytest.mark.parametrize("queue", QUEUES)
    def test_count(self, client, queue):
        r = client.get(f"/api/persons/{queue}/count")
        assert r.status_code == 200
        assert isinstance(r.json()["total"], int)

    @pytest.mark.parametrize("queue", QUEUES)
    def test_list_is_paginated(self, client, queue):
        r = client.get(f"/api/persons/{queue}", params={"page": 1, "per_page": 10})
        assert r.status_code == 200
        body = r.json()
        assert body["page"] == 1
        assert body["per_page"] == 10
        assert "pages" in body

    @pytest.mark.parametrize("queue", QUEUES)
    def test_rejects_per_page_above_ceiling(self, client, queue):
        r = client.get(f"/api/persons/{queue}", params={"per_page": 500})
        assert r.status_code == 422


class TestPersonAdminProjection:
    def test_unknown_person_404(self, client):
        r = client.get("/api/persons/999999999/curation")
        assert r.status_code == 404

    def test_returns_seeded_person(self, client):
        pid = seed_person("AdminProj", "Ec")
        r = client.get(f"/api/persons/{pid}/curation")
        assert r.status_code == 200
        assert r.json()["id"] == pid

    def test_sharing_name_forms_without_sharer(self, client):
        pid = seed_person("Sharing", "Ec")
        _seed_name_form(pid, uniq("sharing ec"))
        r = client.get(f"/api/persons/{pid}/sharing-name-forms")
        assert r.status_code == 200
        assert r.json() == []

    def test_sharing_name_forms_finds_sharer(self, client):
        form = uniq("partagee ec")
        a = seed_person("SharedA", "Ec")
        b = seed_person("SharedB", "Ec")
        _seed_name_form(a, form)
        _seed_name_form(b, form)
        r = client.get(f"/api/persons/{a}/sharing-name-forms")
        assert r.status_code == 200
        assert b in [p["person_id"] for p in r.json()]


class TestMarkPersonsDistinct:
    def test_requires_admin(self, client):
        r = client.post("/api/persons/mark-distinct", json={"person_id_a": 1, "person_id_b": 2})
        assert r.status_code == 401

    def test_marks_pair(self, auth_client):
        a = seed_person("DistinctA", "Ec")
        b = seed_person("DistinctB", "Ec")
        r = auth_client.post(
            "/api/persons/mark-distinct", json={"person_id_a": a, "person_id_b": b}
        )
        assert r.status_code == 200

    def test_rejects_same_person(self, auth_client):
        a = seed_person("DistinctSame", "Ec")
        r = auth_client.post(
            "/api/persons/mark-distinct", json={"person_id_a": a, "person_id_b": a}
        )
        assert r.status_code == 422


# ── Traçabilité des écritures sur les personnes ──────────────


def _audit_personne(event_type: str, aggregate_id: int) -> list[dict]:
    with owner_pool() as cur:
        cur.execute(
            "SELECT payload, user_id FROM audit_log "
            "WHERE event_type = %s AND aggregate_id = %s ORDER BY id",
            (event_type, aggregate_id),
        )
        return cur.fetchall()


class TestTracabilite:
    """Le nom d'une personne et ses identifiants sont ce par quoi les signatures lui reviennent.

    Les changer déplace des publications d'une personne à une autre, sans que rien dans les données ne dise ensuite qui l'a décidé : le rejet et la réattribution d'un identifiant étaient consignés, l'attribution initiale et le changement de nom non.
    """

    def test_le_changement_de_nom_est_consigne(self, auth_client):
        pid = seed_person("AVANT", "A")

        r = auth_client.patch(
            f"/api/persons/{pid}/name", json={"last_name": "APRES", "first_name": "B"}
        )
        assert r.status_code == 200, r.text

        evenements = _audit_personne("person.name_updated", pid)
        assert len(evenements) == 1
        assert evenements[0]["payload"] == {"last_name": "APRES", "first_name": "B"}
        assert evenements[0]["user_id"]

    def test_l_ajout_d_un_identifiant_est_consigne(self, auth_client):
        pid = seed_person()

        r = auth_client.post(
            f"/api/persons/{pid}/identifiers",
            json={"id_type": "orcid", "id_value": "0000-0002-1825-0097"},
        )
        assert r.status_code == 200, r.text

        evenements = _audit_personne("person_identifier.added", pid)
        assert len(evenements) == 1
        assert evenements[0]["payload"] == {
            "id_type": "orcid",
            "id_value": "0000-0002-1825-0097",
            "outcome": "added",
        }

    def test_un_ajout_sans_effet_ne_consigne_rien(self, auth_client):
        """Réattribuer le même identifiant à la même personne ne décide rien : l'appel est idempotent."""
        pid = seed_person()
        corps = {"id_type": "idhal", "id_value": "audit-idempotent"}
        assert auth_client.post(f"/api/persons/{pid}/identifiers", json=corps).status_code == 200
        assert auth_client.post(f"/api/persons/{pid}/identifiers", json=corps).status_code == 200

        assert len(_audit_personne("person_identifier.added", pid)) == 1
