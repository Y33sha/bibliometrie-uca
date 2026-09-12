"""Résolution id → libellé d'une entité de facette (`/api/entity-labels`).

Seed via un pool dédié en autocommit, hors du pool partagé par l'API, avec un nettoyage en fin de module — même stratégie que les autres tests de routers.
"""

import uuid

import pytest

from tests.integration.helpers.db import owner_pool


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    yield
    with owner_pool() as cur:
        cur.execute("TRUNCATE TABLE journals, publishers RESTART IDENTITY CASCADE")


class TestEntityLabels:
    def test_unknown_id(self, client):
        """Un id absent rend un libellé nul, non une erreur : la pastille reste sans nom."""
        r = client.get("/api/entity-labels", params={"kind": "journal", "entity_id": 999999999})
        assert r.status_code == 200
        assert r.json() == {"label": None}

    def test_journal_reads_its_title(self, client):
        title = f"Revue {uuid.uuid4().hex[:8]}"
        with owner_pool() as cur:
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
        with owner_pool() as cur:
            cur.execute(
                "INSERT INTO publishers (name, name_normalized) VALUES (%s, lower(%s)) RETURNING id",
                (name, name),
            )
            publisher_id = cur.fetchone()["id"]
        r = client.get(
            "/api/entity-labels", params={"kind": "publisher", "entity_id": publisher_id}
        )
        assert r.json() == {"label": name}

    def test_person_reads_first_then_last_name(self, client):
        """Le libellé d'une personne est celui que propose la facette des auteurs."""
        with owner_pool() as cur:
            cur.execute(
                "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
                "VALUES ('Dupont', 'Jeanne', 'dupont', 'jeanne') RETURNING id"
            )
            person_id = cur.fetchone()["id"]
        try:
            r = client.get("/api/entity-labels", params={"kind": "person", "entity_id": person_id})
            assert r.json() == {"label": "Jeanne Dupont"}
        finally:
            with owner_pool() as cur:
                cur.execute("DELETE FROM persons WHERE id = %s", (person_id,))

    def test_subject_reads_its_label(self, client):
        label = f"Sujet {uuid.uuid4().hex[:8]}"
        with owner_pool() as cur:
            cur.execute("INSERT INTO subjects (label) VALUES (%s) RETURNING id", (label,))
            subject_id = cur.fetchone()["id"]
        try:
            r = client.get(
                "/api/entity-labels", params={"kind": "subject", "entity_id": subject_id}
            )
            assert r.json() == {"label": label}
        finally:
            with owner_pool() as cur:
                cur.execute("DELETE FROM subjects WHERE id = %s", (subject_id,))

    def test_unknown_kind_rejected(self, client):
        r = client.get("/api/entity-labels", params={"kind": "structure", "entity_id": 1})
        assert r.status_code == 422
