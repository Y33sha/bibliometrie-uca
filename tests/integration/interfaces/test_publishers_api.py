"""Tests de caractérisation pour le router publishers.

Couvre :
- GET /api/publishers (liste + search + sort variants + filtres)
- GET /api/publishers/facets (3 dimensions avec comptes exclusifs)
- GET /api/publishers/{id} (detail enrichi, 404)
- GET /api/publishers/{id}/dashboard (journal_types + doc_types + oa_statuses, 404)
- GET /api/publishers/{id}/subjects (top sujets, exclusion sujets génériques)
- PUT /api/publishers/{id} (update, auth requise)
- POST /api/publishers/{id}/merge (fusion, auth requise, 404 target/source)
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


def _seed_publisher(name: str | None = None) -> int:
    name = name or _uniq("Publisher")
    with _pool() as cur:
        cur.execute(
            "INSERT INTO publishers (name, name_normalized) "
            "VALUES (%s, normalize_name_form(%s)) RETURNING id",
            (name, name),
        )
        return cur.fetchone()["id"]


def _seed_journal(publisher_id: int, title: str | None = None) -> int:
    title = title or _uniq("Journal")
    with _pool() as cur:
        cur.execute(
            "INSERT INTO journals (title, title_normalized, publisher_id) "
            "VALUES (%s, normalize_name_form(%s), %s) RETURNING id",
            (title, title, publisher_id),
        )
        return cur.fetchone()["id"]


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    yield
    with _pool() as cur:
        cur.execute(
            "TRUNCATE TABLE publishers, journals, publications, "
            "publication_subjects, subjects, audit_log "
            "RESTART IDENTITY CASCADE"
        )


# ── GET /api/publishers ─────────────────────────────────────────


class TestListPublishers:
    def test_empty_ok(self, client):
        r = client.get("/api/publishers")
        assert r.status_code == 200
        body = r.json()
        assert "total" in body
        assert "publishers" in body

    def test_pagination(self, client):
        r = client.get("/api/publishers", params={"page": 2, "per_page": 10})
        assert r.status_code == 200

    def test_search_min_length(self, client):
        # search < 2 caractères → ignoré (pas de filtre appliqué)
        r = client.get("/api/publishers", params={"search": "a"})
        assert r.status_code == 200

    def test_search_applied(self, client):
        name = _uniq("Elsevier")
        _seed_publisher(name)
        r = client.get("/api/publishers", params={"search": name.lower()})
        assert r.status_code == 200
        assert any(p["name"] == name for p in r.json()["publishers"])

    def test_search_with_punctuation_normalizes(self, client):
        # `.` ne figure jamais dans name_normalized (normalize_text → espace).
        # La query doit subir la même normalisation pour matcher.
        suffix = _uniq("Punct").split("_")[-1]
        name = f"Acme S.A. Pub {suffix}"
        _seed_publisher(name)
        r = client.get("/api/publishers", params={"search": f"Acme S.A. Pub {suffix}"})
        assert r.status_code == 200
        names = {p["name"] for p in r.json()["publishers"]}
        assert name in names

    def test_doi_prefixes_aggregated(self, client):
        """Les préfixes DOI rattachés à un éditeur sont remontés via JOIN sur doi_prefixes."""
        name = _uniq("PrefixedPub")
        pid = _seed_publisher(name)
        with _pool() as cur:
            cur.execute(
                "INSERT INTO doi_prefixes (prefix, ra, publisher_id, crossref_member_id) "
                "VALUES (%s, %s, %s, %s), (%s, %s, %s, %s)",
                ("10.aaaa", "Crossref", pid, 42, "10.bbbb", "Crossref", pid, 42),
            )
        r = client.get("/api/publishers", params={"search": name.lower()})
        assert r.status_code == 200
        pub = next(p for p in r.json()["publishers"] if p["id"] == pid)
        prefixes = {p["prefix"] for p in pub["doi_prefixes"]}
        assert prefixes == {"10.aaaa", "10.bbbb"}
        assert all(p["ra"] == "Crossref" for p in pub["doi_prefixes"])
        assert all(p["crossref_member_id"] == 42 for p in pub["doi_prefixes"])

    def test_sort_name_desc(self, client):
        r = client.get("/api/publishers", params={"sort": "-name"})
        assert r.status_code == 200

    def test_sort_journals(self, client):
        r = client.get("/api/publishers", params={"sort": "journals"})
        assert r.status_code == 200

    def test_sort_journals_desc(self, client):
        r = client.get("/api/publishers", params={"sort": "-journals"})
        assert r.status_code == 200

    def test_sort_pubs(self, client):
        r = client.get("/api/publishers", params={"sort": "pubs"})
        assert r.status_code == 200

    def test_sort_pubs_desc(self, client):
        r = client.get("/api/publishers", params={"sort": "-pubs"})
        assert r.status_code == 200

    def test_sort_unknown_fallback(self, client):
        # Sort inconnu → fallback sur name ASC
        r = client.get("/api/publishers", params={"sort": "unknown"})
        assert r.status_code == 200

    def test_filter_by_publisher_type(self, client):
        pid = _seed_publisher()
        with _pool() as cur:
            cur.execute("UPDATE publishers SET publisher_type = 'commercial' WHERE id = %s", (pid,))
        r = client.get("/api/publishers", params={"publisher_type": "commercial", "per_page": 200})
        assert r.status_code == 200
        types = {p["publisher_type"] for p in r.json()["publishers"]}
        assert types == {"commercial"}

    def test_filter_by_country(self, client):
        pid = _seed_publisher()
        country = _uniq("XX")[:5]  # code court unique
        with _pool() as cur:
            cur.execute("UPDATE publishers SET country = %s WHERE id = %s", (country, pid))
        r = client.get("/api/publishers", params={"country": country, "per_page": 200})
        assert r.status_code == 200
        countries = {p["country"] for p in r.json()["publishers"]}
        assert countries == {country}

    def test_with_pubs_excludes_orphan_publishers(self, client):
        # Éditeur sans aucune publi rattachée → exclu si with_pubs=true.
        _seed_publisher("OrphanPub")
        # Éditeur avec une revue et une publi → inclus.
        with_data = _seed_publisher("WithPubsPub")
        jid = _seed_journal(with_data)
        with _pool() as cur:
            cur.execute(
                "INSERT INTO publications (title, pub_year, journal_id) VALUES ('p1', 2024, %s)",
                (jid,),
            )
        r = client.get("/api/publishers", params={"with_pubs": "true", "per_page": 200})
        assert r.status_code == 200
        names = {p["name"] for p in r.json()["publishers"]}
        assert "WithPubsPub" in names
        assert "OrphanPub" not in names

    def test_with_pubs_default_false_includes_orphans(self, client):
        # Sans le flag, on liste tout comme avant.
        _seed_publisher("OrphanDefault")
        r = client.get("/api/publishers", params={"per_page": 200})
        assert r.status_code == 200
        names = {p["name"] for p in r.json()["publishers"]}
        assert "OrphanDefault" in names

    def test_filter_by_is_predatory(self, client):
        pid = _seed_publisher()
        with _pool() as cur:
            cur.execute("UPDATE publishers SET is_predatory = TRUE WHERE id = %s", (pid,))
        r = client.get("/api/publishers", params={"is_predatory": "true", "per_page": 200})
        assert r.status_code == 200
        flags = {p["is_predatory"] for p in r.json()["publishers"]}
        assert flags == {True}


# ── GET /api/publishers/facets ───────────────────────────────────


class TestPublishersFacets:
    def test_returns_3_dimensions(self, client):
        pid = _seed_publisher()
        country = _uniq("ZZ")[:5]
        with _pool() as cur:
            cur.execute("UPDATE publishers SET country = %s WHERE id = %s", (country, pid))
        r = client.get("/api/publishers/facets")
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"publisher_types", "countries", "predatory"}
        # Le pays seedé doit apparaître dans la facette countries.
        assert any(opt["value"] == country for opt in body["countries"])
        # `predatory` est un bool : 2 options Oui/Non.
        assert sorted(o["value"] for o in body["predatory"]) == ["false", "true"]


# ── GET /api/publishers/{id} ────────────────────────────────────


class TestGetPublisher:
    def test_404(self, client):
        r = client.get("/api/publishers/999999999")
        assert r.status_code == 404

    def test_returns_existing_with_detail_keys(self, client):
        pid = _seed_publisher("TestGetPub")
        r = client.get(f"/api/publishers/{pid}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == pid
        assert body["name"] == "TestGetPub"
        # Champs ajoutés par la promotion vers PublisherDetailResponse.
        assert "publisher_type" in body
        assert "doi_prefixes" in body
        assert "journal_count" in body
        assert "pub_count" in body
        assert body["journal_count"] == 0
        assert body["pub_count"] == 0


# ── GET /api/publishers/{id}/dashboard ──────────────────────────


class TestPublisherDashboard:
    def test_404_when_unknown(self, client):
        r = client.get("/api/publishers/999999999/dashboard")
        assert r.status_code == 404

    def test_empty_distributions_for_publisher_without_journals(self, client):
        pid = _seed_publisher()
        r = client.get(f"/api/publishers/{pid}/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert body == {
            "total_publications": 0,
            "journal_types": [],
            "doc_types": [],
            "oa_statuses": [],
        }

    def test_aggregates_journals_and_publications(self, client):
        pid = _seed_publisher()
        j_journal = _seed_journal(pid)
        j_proc = _seed_journal(pid)
        with _pool() as cur:
            cur.execute(
                "UPDATE journals SET journal_type = 'proceedings' WHERE id = %s",
                (j_proc,),
            )
            cur.execute(
                "INSERT INTO publications (title, pub_year, doc_type, oa_status, journal_id) "
                "VALUES ('p1', 2024, 'article', 'gold', %s), "
                "       ('p2', 2024, 'article', 'closed', %s), "
                "       ('p3', 2024, 'conference_paper', NULL, %s)",
                (j_journal, j_journal, j_proc),
            )
        r = client.get(f"/api/publishers/{pid}/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert body["total_publications"] == 3
        jt = {(j["journal_type"], j["count"]) for j in body["journal_types"]}
        assert jt == {("journal", 1), ("proceedings", 1)}
        dt = {(d["doc_type"], d["count"]) for d in body["doc_types"]}
        assert dt == {("article", 2), ("conference_paper", 1)}
        oa = {(o["oa_status"], o["count"]) for o in body["oa_statuses"]}
        assert oa == {("gold", 1), ("closed", 1), (None, 1)}


# ── GET /api/publishers/{id}/subjects ───────────────────────────


class TestPublisherSubjects:
    def test_returns_empty_for_publisher_without_pubs(self, client):
        pid = _seed_publisher()
        r = client.get(f"/api/publishers/{pid}/subjects")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_top_subjects_excluding_generic(self, client):
        pid = _seed_publisher()
        jid = _seed_journal(pid)
        with _pool() as cur:
            cur.execute(
                "INSERT INTO publications (title, pub_year, journal_id) "
                "VALUES ('p1', 2024, %s), ('p2', 2024, %s) RETURNING id",
                (jid, jid),
            )
            pub_ids = [r["id"] for r in cur.fetchall()]
            specific_label = _uniq("specific_subject")
            cur.execute(
                "INSERT INTO subjects (label, usage_count) VALUES (%s, 100) RETURNING id",
                (specific_label,),
            )
            spec_id = cur.fetchone()["id"]
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
        r = client.get(f"/api/publishers/{pid}/subjects")
        assert r.status_code == 200
        body = r.json()
        labels = {s["label"] for s in body}
        assert specific_label in labels
        assert generic_label not in labels
        spec_entry = next(s for s in body if s["label"] == specific_label)
        assert spec_entry["count"] == 2

    def test_limit_above_max_rejected(self, client):
        pid = _seed_publisher()
        r = client.get(f"/api/publishers/{pid}/subjects", params={"limit": 500})
        assert r.status_code == 422


# ── PUT /api/publishers/{id} ────────────────────────────────────


class TestUpdatePublisher:
    def test_requires_admin(self, client):
        r = client.put("/api/publishers/1", json={"name": "Updated"})
        assert r.status_code == 401

    def test_ok(self, auth_client):
        pid = _seed_publisher()
        r = auth_client.put(
            f"/api/publishers/{pid}",
            json={
                "name": "UpdatedName",
                "country": "FR",
                "is_predatory": False,
            },
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ── POST /api/publishers/{id}/merge ─────────────────────────────


class TestMergePublishers:
    def test_requires_admin(self, client):
        r = client.post("/api/publishers/1/merge", json={"source_id": 2})
        assert r.status_code == 401

    def test_target_not_found(self, auth_client):
        src = _seed_publisher()
        r = auth_client.post("/api/publishers/999999999/merge", json={"source_id": src})
        assert r.status_code == 404

    def test_source_not_found(self, auth_client):
        dst = _seed_publisher()
        r = auth_client.post(f"/api/publishers/{dst}/merge", json={"source_id": 999999998})
        assert r.status_code == 404

    def test_ok(self, auth_client):
        src = _seed_publisher("MergeSrc")
        dst = _seed_publisher("MergeDst")
        r = auth_client.post(f"/api/publishers/{dst}/merge", json={"source_id": src})
        assert r.status_code == 200
        body = r.json()
        assert body["merged"] is True
        assert body["source_id"] == src
        assert body["target_id"] == dst


# ── GET /api/publisher-types ────────────────────────────────────


class TestPublisherTypes:
    def test_returns_all_values_with_labels(self, client):
        r = client.get("/api/publisher-types")
        assert r.status_code == 200
        body = r.json()
        values = [opt["value"] for opt in body]
        assert values == [
            "commercial",
            "learned_society",
            "academic_institution",
            "repository",
            "aggregator",
            "unknown",
        ]
        assert all("label_fr" in opt and opt["label_fr"] for opt in body)
