"""Résolution id → libellé d'une entité de facette (`/api/entity-labels`).

Seed via un pool dédié en autocommit, hors du pool partagé par l'API, avec un nettoyage en fin de module — même stratégie que les autres tests de routers.
"""

import uuid

from tests.integration.helpers.db import owner_pool
from tests.integration.helpers.seeds import (
    seed_person,
    seed_publisher,
    seed_serial,
    seed_subject,
)


class TestEntityLabels:
    def test_unknown_id(self, client):
        """Un id absent rend un libellé nul, non une erreur : la pastille reste sans nom."""
        r = client.get("/api/entity-labels", params={"kind": "serial", "entity_id": 999999999})
        assert r.status_code == 200
        assert r.json() == {"label": None}

    def test_serial_reads_its_title(self, client):
        title = f"Revue {uuid.uuid4().hex[:8]}"
        serial_id = seed_serial(title, title_normalized=title.lower())
        r = client.get("/api/entity-labels", params={"kind": "serial", "entity_id": serial_id})
        assert r.json() == {"label": title}

    def test_publisher_reads_its_name(self, client):
        """Le libellé d'un éditeur se lit dans `name`, là où celui d'une revue se lit dans `title`."""
        name = f"Editeur {uuid.uuid4().hex[:8]}"
        publisher_id = seed_publisher(name, name_normalized=name.lower())
        r = client.get(
            "/api/entity-labels", params={"kind": "publisher", "entity_id": publisher_id}
        )
        assert r.json() == {"label": name}

    def test_person_reads_first_then_last_name(self, client):
        """Le libellé d'une personne est celui que propose la facette des auteurs."""
        person_id = seed_person("Dupont", "Jeanne")
        try:
            r = client.get("/api/entity-labels", params={"kind": "person", "entity_id": person_id})
            assert r.json() == {"label": "Jeanne Dupont"}
        finally:
            with owner_pool() as cur:
                cur.execute("DELETE FROM persons WHERE id = %s", (person_id,))

    def test_subject_reads_its_label(self, client):
        label = f"Sujet {uuid.uuid4().hex[:8]}"
        subject_id = seed_subject(label)
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
