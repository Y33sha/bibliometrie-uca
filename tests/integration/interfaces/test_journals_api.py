"""Tests d'intégration pour le router `interfaces.api.routers.journals`.

Couvre :
- GET /api/journals (liste, search, publisher filter, sort variants)
- GET /api/journals/{id} (detail enrichi avec DOAJ, 404)
- GET /api/journals/{id}/dashboard (distributions doc_type + oa_status, 404)
- GET /api/journals/{id}/subjects (top sujets, exclusion sujets génériques)
- PUT /api/journals/{id} (update, auth requise, 404)
- POST /api/journals/{id}/merge (auth requise, 404 target/source, happy)
"""

from __future__ import annotations

import json
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


def _seed_publisher(name: str | None = None) -> int:
    name = name or _uniq("Publisher")
    with _pool() as cur:
        cur.execute(
            "INSERT INTO publishers (name, name_normalized) VALUES (%s, lower(%s)) RETURNING id",
            (name, name),
        )
        return cur.fetchone()["id"]


def _seed_journal(title: str | None = None, publisher_id: int | None = None) -> int:
    title = title or _uniq("Journal")
    with _pool() as cur:
        cur.execute(
            "INSERT INTO journals (title, title_normalized, publisher_id) "
            "VALUES (%s, lower(%s), %s) RETURNING id",
            (title, title, publisher_id),
        )
        return cur.fetchone()["id"]


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    yield
    with _pool() as cur:
        cur.execute(
            "TRUNCATE TABLE journals, publishers, publications, "
            "publication_subjects, subjects, audit_log "
            "RESTART IDENTITY CASCADE"
        )


class TestListJournals:
    def test_returns_200_with_paginated_shape(self, client):
        r = client.get("/api/journals")
        assert r.status_code == 200
        body = r.json()
        assert {"total", "page", "pages", "journals"} <= set(body)

    def test_pagination_params(self, client):
        r = client.get("/api/journals", params={"page": 2, "per_page": 5})
        assert r.status_code == 200
        body = r.json()
        assert body["page"] == 2

    def test_search_min_length_ignored(self, client):
        # search < 2 caractères : pas de filtre appliqué.
        r = client.get("/api/journals", params={"search": "a"})
        assert r.status_code == 200

    def test_search_applied(self, client):
        title = _uniq("ElsevierJournal")
        _seed_journal(title)
        r = client.get("/api/journals", params={"search": title.lower()})
        assert r.status_code == 200
        assert any(j["title"] == title for j in r.json()["journals"])

    def test_filter_by_publisher(self, client):
        pub = _seed_publisher()
        j = _seed_journal(publisher_id=pub)
        r = client.get("/api/journals", params={"publisher_id": pub})
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["journals"]]
        assert j in ids

    @pytest.mark.parametrize(
        "sort",
        ["title", "-title", "publisher", "-publisher", "pubs", "-pubs", "unknown"],
    )
    def test_sort_variants(self, client, sort):
        # `unknown` doit fallback sur `title` ASC sans 500.
        r = client.get("/api/journals", params={"sort": sort})
        assert r.status_code == 200

    def test_per_page_above_limit_rejected(self, client):
        # `per_page` Query(le=200) → > 200 = 422.
        r = client.get("/api/journals", params={"per_page": 500})
        assert r.status_code == 422


class TestGetJournal:
    def test_404_when_unknown(self, client):
        r = client.get("/api/journals/999999999")
        assert r.status_code == 404

    def test_returns_existing_with_detail_keys(self, client):
        title = _uniq("DetailJournal")
        jid = _seed_journal(title)
        r = client.get(f"/api/journals/{jid}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == jid
        assert body["title"] == title
        # Champs ajoutés par la promotion vers JournalDetailResponse.
        assert "doaj_payload" in body
        assert "doaj_imported_at" in body
        assert "pub_count" in body
        assert body["doaj_payload"] is None
        assert body["pub_count"] == 0

    def test_doaj_payload_exposed_when_present(self, client):
        jid = _seed_journal()
        payload = {"License": "CC BY", "Country of publisher": "France"}
        with _pool() as cur:
            cur.execute(
                "UPDATE journals SET doaj_payload = %s::jsonb, is_in_doaj = TRUE WHERE id = %s",
                (json.dumps(payload), jid),
            )
        r = client.get(f"/api/journals/{jid}")
        assert r.status_code == 200
        body = r.json()
        assert body["is_in_doaj"] is True
        assert body["doaj_payload"] == payload


class TestJournalDashboard:
    def test_404_when_unknown(self, client):
        r = client.get("/api/journals/999999999/dashboard")
        assert r.status_code == 404

    def test_returns_distributions_for_journal_without_pubs(self, client):
        jid = _seed_journal()
        r = client.get(f"/api/journals/{jid}/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert body == {"total_publications": 0, "doc_types": [], "oa_statuses": []}

    def test_aggregates_publications(self, client):
        jid = _seed_journal()
        with _pool() as cur:
            cur.execute(
                "INSERT INTO publications (title, pub_year, doc_type, oa_status, journal_id) "
                "VALUES ('p1', 2024, 'article', 'gold', %s), "
                "       ('p2', 2024, 'article', 'closed', %s), "
                "       ('p3', 2024, 'preprint', NULL, %s)",
                (jid, jid, jid),
            )
        r = client.get(f"/api/journals/{jid}/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert body["total_publications"] == 3
        dt = {(d["doc_type"], d["count"]) for d in body["doc_types"]}
        assert dt == {("article", 2), ("preprint", 1)}
        oa = {(o["oa_status"], o["count"]) for o in body["oa_statuses"]}
        assert oa == {("gold", 1), ("closed", 1), (None, 1)}


class TestJournalSubjects:
    def test_returns_empty_for_journal_without_pubs(self, client):
        jid = _seed_journal()
        r = client.get(f"/api/journals/{jid}/subjects")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_top_subjects_excluding_generic(self, client):
        jid = _seed_journal()
        with _pool() as cur:
            cur.execute(
                "INSERT INTO publications (title, pub_year, journal_id) "
                "VALUES ('p1', 2024, %s), ('p2', 2024, %s) RETURNING id",
                (jid, jid),
            )
            pub_ids = [r["id"] for r in cur.fetchall()]
            # Sujet spécifique (sous le seuil 5000) attaché aux 2 publis.
            specific_label = _uniq("specific_subject")
            cur.execute(
                "INSERT INTO subjects (label, usage_count) VALUES (%s, 100) RETURNING id",
                (specific_label,),
            )
            spec_id = cur.fetchone()["id"]
            # Sujet trop générique (au-dessus du seuil) attaché à 1 publi —
            # doit être exclu du top.
            generic_label = _uniq("generic_subject")
            cur.execute(
                "INSERT INTO subjects (label, usage_count) VALUES (%s, 9999) RETURNING id",
                (generic_label,),
            )
            gen_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO publication_subjects (publication_id, subject_id, source) "
                "VALUES (%s, %s, 'hal'), (%s, %s, 'hal'), (%s, %s, 'hal')",
                (pub_ids[0], spec_id, pub_ids[1], spec_id, pub_ids[0], gen_id),
            )
        r = client.get(f"/api/journals/{jid}/subjects")
        assert r.status_code == 200
        body = r.json()
        labels = {s["label"] for s in body}
        assert specific_label in labels
        assert generic_label not in labels
        spec_entry = next(s for s in body if s["label"] == specific_label)
        assert spec_entry["count"] == 2

    def test_respects_limit(self, client):
        jid = _seed_journal()
        r = client.get(f"/api/journals/{jid}/subjects", params={"limit": 5})
        assert r.status_code == 200
        # Tableau vide pour ce jid neuf ; on vérifie surtout que limit=5 est accepté.
        assert r.json() == []

    def test_limit_above_max_rejected(self, client):
        jid = _seed_journal()
        r = client.get(f"/api/journals/{jid}/subjects", params={"limit": 500})
        assert r.status_code == 422


class TestUpdateJournal:
    def test_requires_admin(self, client):
        r = client.put("/api/journals/1", json={"title": "X"})
        assert r.status_code == 401

    def test_updates_partial_fields(self, auth_client):
        jid = _seed_journal()
        r = auth_client.put(
            f"/api/journals/{jid}",
            json={
                "title": "UpdatedTitle",
                "is_predatory": True,
            },
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        # Vérifier en base que seuls les champs envoyés sont écrits.
        with _pool() as cur:
            cur.execute("SELECT title, is_predatory FROM journals WHERE id = %s", (jid,))
            row = cur.fetchone()
            assert row["title"] == "UpdatedTitle"
            assert row["is_predatory"] is True


class TestMergeJournals:
    def test_requires_admin(self, client):
        r = client.post("/api/journals/1/merge", json={"source_id": 2})
        assert r.status_code == 401

    def test_404_when_target_missing(self, auth_client):
        src = _seed_journal()
        r = auth_client.post("/api/journals/999999999/merge", json={"source_id": src})
        assert r.status_code == 404
        assert "cible" in r.json()["detail"]

    def test_404_when_source_missing(self, auth_client):
        dst = _seed_journal()
        r = auth_client.post(f"/api/journals/{dst}/merge", json={"source_id": 999999998})
        assert r.status_code == 404
        assert "source" in r.json()["detail"]

    def test_happy_path(self, auth_client):
        src = _seed_journal("MergeSrc")
        dst = _seed_journal("MergeDst")
        r = auth_client.post(f"/api/journals/{dst}/merge", json={"source_id": src})
        assert r.status_code == 200
        body = r.json()
        assert body == {"merged": True, "source_id": src, "target_id": dst}
        # Source supprimée, target conservée.
        with _pool() as cur:
            cur.execute("SELECT id FROM journals WHERE id IN (%s, %s)", (src, dst))
            ids = {row["id"] for row in cur.fetchall()}
            assert dst in ids
            assert src not in ids


# ── GET /api/journal-types ──────────────────────────────────────


class TestJournalTypes:
    def test_returns_all_values_with_labels(self, client):
        r = client.get("/api/journal-types")
        assert r.status_code == 200
        body = r.json()
        values = [opt["value"] for opt in body]
        assert values == [
            "journal",
            "proceedings",
            "repository",
            "book_series",
            "preprint_server",
            "media",
        ]
        assert all("label_fr" in opt and opt["label_fr"] for opt in body)
