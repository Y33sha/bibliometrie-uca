"""Tests de caractérisation pour le router publishers.

Couvre :
- GET /api/publishers (liste + search + sort variants + filtres)
- GET /api/publishers/facets (3 dimensions avec comptes exclusifs)
- GET /api/publishers/{id} (detail enrichi, 404)
- GET /api/publishers/{id}/dashboard (serial_types + doc_types + oa_statuses, 404)
- GET /api/publishers/{id}/subjects (top sujets, exclusion sujets génériques)
- PUT /api/publishers/{id} (update, auth requise)
- POST /api/publishers/{id}/merge (fusion, auth requise, 404 target/source)
"""

import uuid
from functools import partial

from tests.integration.helpers.db import owner_pool
from tests.integration.helpers.seeds import (
    seed_country,
    seed_doi_prefix,
    seed_in_perimeter_contributions,
    seed_publication,
    seed_publication_subject,
    seed_publisher,
    seed_serial,
    seed_subject,
    uniq,
)

# Publication sans titre normalisé.
_publication = partial(seed_publication, normalize_title=False)


def _seed_doi_prefix(publisher_id: int, *, crossref_member_id: int) -> str:
    prefix = f"10.{uuid.uuid4().int % 100000:05d}"
    seed_doi_prefix(
        prefix, ra="Crossref", publisher_id=publisher_id, crossref_member_id=crossref_member_id
    )
    return prefix


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
        name = uniq("Elsevier")
        seed_publisher(name)
        r = client.get("/api/publishers", params={"search": name.lower()})
        assert r.status_code == 200
        assert any(p["name"] == name for p in r.json()["publishers"])

    def test_search_with_punctuation_normalizes(self, client):
        # `.` ne figure jamais dans name_normalized (normalize_text → espace).
        # La query doit subir la même normalisation pour matcher.
        suffix = uniq("Punct").split("_")[-1]
        name = f"Acme S.A. Pub {suffix}"
        seed_publisher(name)
        r = client.get("/api/publishers", params={"search": f"Acme S.A. Pub {suffix}"})
        assert r.status_code == 200
        names = {p["name"] for p in r.json()["publishers"]}
        assert name in names

    def test_sort_name_desc(self, client):
        r = client.get("/api/publishers", params={"sort": "name_desc"})
        assert r.status_code == 200

    def test_sort_serials(self, client):
        r = client.get("/api/publishers", params={"sort": "serials_asc"})
        assert r.status_code == 200

    def test_sort_serials_desc(self, client):
        r = client.get("/api/publishers", params={"sort": "serials_desc"})
        assert r.status_code == 200

    def test_sort_publications(self, client):
        r = client.get("/api/publishers", params={"sort": "publications_asc"})
        assert r.status_code == 200

    def test_sort_publications_desc(self, client):
        r = client.get("/api/publishers", params={"sort": "publications_desc"})
        assert r.status_code == 200

    def test_sort_outside_the_vocabulary_is_refused(self, client):
        r = client.get("/api/publishers", params={"sort": "unknown"})
        assert r.status_code == 422

    def test_filter_by_publisher_type(self, client):
        pid = seed_publisher()
        with owner_pool() as cur:
            cur.execute("UPDATE publishers SET publisher_type = 'commercial' WHERE id = %s", (pid,))
        r = client.get("/api/publishers", params={"publisher_type": "commercial", "per_page": 200})
        assert r.status_code == 200
        types = {p["publisher_type"] for p in r.json()["publishers"]}
        assert types == {"commercial"}

    def test_filter_by_country(self, client):
        pid = seed_publisher()
        country = uniq("XX")[:5]  # code court unique
        with owner_pool() as cur:
            cur.execute("UPDATE publishers SET country = %s WHERE id = %s", (country, pid))
        r = client.get("/api/publishers", params={"country": country, "per_page": 200})
        assert r.status_code == 200
        countries = {p["country"] for p in r.json()["publishers"]}
        assert countries == {country}

    def _seed_with_and_without_publications(self) -> None:
        seed_publisher("OrphanPub")
        with_data = seed_publisher("WithPubsPub")
        jid = seed_serial(publisher_id=with_data)
        _publication("p1", serial_id=jid)
        seed_in_perimeter_contributions(jid)

    def _names(self, client, **params) -> set[str]:
        r = client.get("/api/publishers", params={"per_page": 200, **params})
        assert r.status_code == 200
        return {p["name"] for p in r.json()["publishers"]}

    def test_has_publications_true_excludes_orphans(self, client):
        self._seed_with_and_without_publications()
        names = self._names(client, has_publications="true")
        assert "WithPubsPub" in names
        assert "OrphanPub" not in names

    def test_has_publications_false_keeps_orphans_only(self, client):
        self._seed_with_and_without_publications()
        names = self._names(client, has_publications="false")
        assert "OrphanPub" in names
        assert "WithPubsPub" not in names

    def test_has_publications_absent_lists_all(self, client):
        self._seed_with_and_without_publications()
        assert {"OrphanPub", "WithPubsPub"} <= self._names(client)


# ── GET /api/publishers/facets ───────────────────────────────────


class TestPublishersFacets:
    def test_returns_2_dimensions(self, client):
        pid = seed_publisher()
        country = uniq("ZZ")[:5]
        with owner_pool() as cur:
            cur.execute("UPDATE publishers SET country = %s WHERE id = %s", (country, pid))
        r = client.get("/api/publishers/facets")
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"publisher_types", "countries", "publications"}
        # Le pays seedé doit apparaître dans la facette countries.
        assert any(opt["value"] == country for opt in body["countries"])

    def test_country_label_is_the_country_name(self, client):
        seed_country("fr", "France")
        with owner_pool() as cur:
            cur.execute("UPDATE publishers SET country = 'fr' WHERE id = %s", (seed_publisher(),))
        r = client.get("/api/publishers/facets")
        assert r.status_code == 200
        labels = {opt["value"]: opt["label"] for opt in r.json()["countries"]}
        assert labels["fr"] == "France"

    def test_country_label_falls_back_to_the_code(self, client):
        country = uniq("QQ")[:5]
        with owner_pool() as cur:
            cur.execute(
                "UPDATE publishers SET country = %s WHERE id = %s", (country, seed_publisher())
            )
        r = client.get("/api/publishers/facets")
        labels = {opt["value"]: opt["label"] for opt in r.json()["countries"]}
        assert labels[country] == country.upper()

    def test_publications_counts_ignore_their_own_filter(self, client):
        country = uniq("YY")[:5]
        orphan = seed_publisher()
        with_data = seed_publisher()
        jid = seed_serial(publisher_id=with_data)
        _publication("p1", serial_id=jid)
        seed_in_perimeter_contributions(jid)
        with owner_pool() as cur:
            cur.execute(
                "UPDATE publishers SET country = %s WHERE id = ANY(%s)",
                (country, [orphan, with_data]),
            )
        r = client.get(
            "/api/publishers/facets", params={"country": country, "has_publications": "true"}
        )
        assert r.status_code == 200
        assert r.json()["publications"] == {"yes": 1, "no": 1}


# ── GET /api/publishers/{id} ────────────────────────────────────


class TestGetPublisher:
    def test_404(self, client):
        r = client.get("/api/publishers/999999999")
        assert r.status_code == 404

    def test_returns_existing_with_detail_keys(self, client):
        pid = seed_publisher("TestGetPub")
        r = client.get(f"/api/publishers/{pid}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == pid
        assert body["name"] == "TestGetPub"
        # Le profil détaillé porte le type, les préfixes DOI et les décomptes.
        assert "publisher_type" in body
        assert "doi_prefixes" in body
        assert "serial_count" in body
        assert "publication_count" in body
        assert body["serial_count"] == 0
        assert body["publication_count"] == 0

    def test_doi_prefixes_aggregated(self, client):
        """Les préfixes DOI rattachés à un éditeur sont remontés sur la page détail."""
        name = uniq("PrefixedPub")
        pid = seed_publisher(name)
        for prefix in ("10.9008", "10.9009"):
            seed_doi_prefix(prefix, ra="Crossref", publisher_id=pid, crossref_member_id=42)
        r = client.get(f"/api/publishers/{pid}")
        assert r.status_code == 200
        publication = r.json()
        prefixes = {p["prefix"] for p in publication["doi_prefixes"]}
        assert prefixes == {"10.9008", "10.9009"}
        assert all(p["ra"] == "Crossref" for p in publication["doi_prefixes"])
        assert all(p["crossref_member_id"] == 42 for p in publication["doi_prefixes"])

    def test_doi_prefixes_in_list(self, client):
        """Régression : la colonne « Préfixes DOI » du tableau des éditeurs restait vide, la liste ne les renvoyant pas."""
        name = uniq("ListedPrefixedPub")
        pid = seed_publisher(name)
        seed_doi_prefix("10.9010", ra="Crossref", publisher_id=pid)
        r = client.get("/api/publishers", params={"search": name})
        assert r.status_code == 200
        mine = next(p for p in r.json()["publishers"] if p["id"] == pid)
        assert [p["prefix"] for p in mine["doi_prefixes"]] == ["10.9010"]


# ── GET /api/publishers/{id}/dashboard ──────────────────────────


class TestPublisherDashboard:
    def test_404_when_unknown(self, client):
        r = client.get("/api/publishers/999999999/dashboard")
        assert r.status_code == 404

    def test_empty_distributions_for_publisher_without_serials(self, client):
        pid = seed_publisher()
        r = client.get(f"/api/publishers/{pid}/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert body == {
            "total_publications": 0,
            "serial_types": [],
            "doc_types": [],
            "oa_statuses": [],
        }

    def test_aggregates_serials_and_publications(self, client):
        pid = seed_publisher()
        j_serial = seed_serial(publisher_id=pid)
        j_proc = seed_serial(publisher_id=pid)
        with owner_pool() as cur:
            cur.execute(
                "UPDATE serials SET serial_type = 'journal' WHERE id = %s",
                (j_serial,),
            )
            cur.execute(
                "UPDATE serials SET serial_type = 'proceedings' WHERE id = %s",
                (j_proc,),
            )
            _publication(
                "p1", doc_type="article", oa_status="gold", serial_id=j_serial, publisher_id=pid
            )
            _publication(
                "p2", doc_type="article", oa_status="closed", serial_id=j_serial, publisher_id=pid
            )
            _publication(
                "p3",
                doc_type="conference_paper",
                oa_status=None,
                serial_id=j_proc,
                publisher_id=pid,
            )
        seed_in_perimeter_contributions(j_serial)
        seed_in_perimeter_contributions(j_proc)
        r = client.get(f"/api/publishers/{pid}/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert body["total_publications"] == 3
        jt = {(j["serial_type"], j["count"]) for j in body["serial_types"]}
        assert jt == {("journal", 1), ("proceedings", 1)}
        dt = {(d["doc_type"], d["count"]) for d in body["doc_types"]}
        assert dt == {("article", 2), ("conference_paper", 1)}
        oa = {(o["oa_status"], o["count"]) for o in body["oa_statuses"]}
        assert oa == {("gold", 1), ("closed", 1), (None, 1)}


# ── GET /api/publishers/{id}/subjects ───────────────────────────


class TestPublisherSubjects:
    def test_returns_empty_for_publisher_without_publications(self, client):
        pid = seed_publisher()
        r = client.get(f"/api/publishers/{pid}/subjects")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_top_subjects_excluding_generic(self, client):
        pid = seed_publisher()
        jid = seed_serial(publisher_id=pid)
        publication_ids = [
            _publication("p1", serial_id=jid, publisher_id=pid),
            _publication("p2", serial_id=jid, publisher_id=pid),
        ]
        specific_label = uniq("specific_subject")
        spec_id = seed_subject(specific_label, usage_count=100)
        generic_label = uniq("generic_subject")
        gen_id = seed_subject(generic_label, usage_count=9999)
        for publication_id, subject_id in (
            (publication_ids[0], spec_id),
            (publication_ids[1], spec_id),
            (publication_ids[0], gen_id),
        ):
            seed_publication_subject(publication_id, subject_id=subject_id)
        seed_in_perimeter_contributions(jid)
        r = client.get(f"/api/publishers/{pid}/subjects")
        assert r.status_code == 200
        body = r.json()
        labels = {s["label"] for s in body}
        assert specific_label in labels
        assert generic_label not in labels
        spec_entry = next(s for s in body if s["label"] == specific_label)
        assert spec_entry["count"] == 2

    def test_limit_above_max_rejected(self, client):
        pid = seed_publisher()
        r = client.get(f"/api/publishers/{pid}/subjects", params={"limit": 500})
        assert r.status_code == 422


# ── PUT /api/publishers/{id} ────────────────────────────────────


class TestUpdatePublisher:
    def test_requires_admin(self, client):
        r = client.put("/api/publishers/1", json={"name": "Updated"})
        assert r.status_code == 401

    def test_ok(self, auth_client):
        pid = seed_publisher()
        r = auth_client.put(
            f"/api/publishers/{pid}",
            json={
                "name": "UpdatedName",
                "country": "FR",
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
        src = seed_publisher()
        r = auth_client.post("/api/publishers/999999999/merge", json={"source_id": src})
        assert r.status_code == 404

    def test_source_not_found(self, auth_client):
        dst = seed_publisher()
        r = auth_client.post(f"/api/publishers/{dst}/merge", json={"source_id": 999999998})
        assert r.status_code == 404

    def test_ok(self, auth_client):
        src = seed_publisher("MergeSrc")
        dst = seed_publisher("MergeDst")
        r = auth_client.post(f"/api/publishers/{dst}/merge", json={"source_id": src})
        assert r.status_code == 200
        body = r.json()
        assert body["merged"] is True
        assert body["source_id"] == src
        assert body["target_id"] == dst

    def test_refused_on_distinct_crossref_members(self, auth_client):
        src = seed_publisher("MembreSrc")
        dst = seed_publisher("MembreDst")
        _seed_doi_prefix(src, crossref_member_id=793)
        _seed_doi_prefix(dst, crossref_member_id=297)
        r = auth_client.post(f"/api/publishers/{dst}/merge", json={"source_id": src})
        assert r.status_code == 409
        assert "793" in r.json()["detail"]

    def test_merges_when_a_crossref_member_is_shared(self, auth_client):
        src = seed_publisher("MembrePartageSrc")
        dst = seed_publisher("MembrePartageDst")
        _seed_doi_prefix(src, crossref_member_id=297)
        _seed_doi_prefix(dst, crossref_member_id=297)
        r = auth_client.post(f"/api/publishers/{dst}/merge", json={"source_id": src})
        assert r.status_code == 200


# ── GET /api/publishers/types ───────────────────────────────────


class TestPublisherTypes:
    def test_returns_all_values_with_labels(self, client):
        r = client.get("/api/publishers/types")
        assert r.status_code == 200
        body = r.json()
        values = [opt["value"] for opt in body]
        assert values == [
            "commercial",
            "learned_society",
            "academic_institution",
            "repository",
            "aggregator",
            "media",
            "unknown",
        ]
        assert all("label_fr" in opt and opt["label_fr"] for opt in body)


# ── Traçabilité des écritures sur les éditeurs ───────────────


class TestTracabilite:
    """La fusion de deux éditeurs était consignée, la modification de l'un d'eux non.

    Renommer un éditeur ou changer son pays déplace les décomptes qui s'agrègent par éditeur, et efface la valeur antérieure sans laisser dire qui l'a décidé.
    """

    def test_la_modification_ne_consigne_que_les_champs_fournis(self, auth_client):
        pid = seed_publisher(uniq("Audit éditeur"))

        r = auth_client.put(f"/api/publishers/{pid}", json={"country": "FR"})
        assert r.status_code == 200, r.text

        with owner_pool() as cur:
            cur.execute(
                "SELECT payload, user_id FROM audit_log "
                "WHERE event_type = 'publisher.updated' AND aggregate_id = %s ORDER BY id",
                (pid,),
            )
            evenements = cur.fetchall()

        assert len(evenements) == 1
        # Le pays est normalisé au bord : la trace porte la valeur écrite, non la casse reçue.
        assert evenements[0]["payload"] == {"country": "fr"}
        assert evenements[0]["user_id"]
