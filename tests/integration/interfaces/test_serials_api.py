"""Tests d'intégration pour le router `interfaces.api.routers.serials`.

Couvre :
- GET /api/serials (liste, recherche titre et ISSN, publisher filter, sort variants)
- GET /api/serials/facets/entities (facette éditeur contextuelle)
- GET /api/serials/{id} (detail enrichi avec DOAJ, 404)
- GET /api/serials/{id}/dashboard (distributions doc_type + oa_status, 404)
- GET /api/serials/{id}/subjects (top sujets, exclusion sujets génériques)
- PUT /api/serials/{id} (update, auth requise, 404)
- POST /api/serials/{id}/merge (auth requise, 404 target/source, happy)
"""

from __future__ import annotations

import json
import uuid
from functools import partial

import pytest

from tests.integration.helpers.db import owner_pool
from tests.integration.helpers.seeds import (
    seed_in_perimeter_contributions,
    seed_publication,
    seed_publication_subject,
    seed_publisher,
    seed_serial,
    seed_serial_doi_namespace,
    seed_serial_issn,
    seed_source_record,
    seed_subject,
    uniq,
)

# Publication sans titre normalisé.
_publication = partial(seed_publication, normalize_title=False)

# Enregistrement source de titre « Doc », sans année.
_seed_record = partial(seed_source_record, title="Doc", publication_year=None)


class TestListSerials:
    def test_returns_200_with_paginated_shape(self, client):
        r = client.get("/api/serials")
        assert r.status_code == 200
        body = r.json()
        assert {"total", "page", "pages", "serials"} <= set(body)

    def test_pagination_params(self, client):
        r = client.get("/api/serials", params={"page": 2, "per_page": 5})
        assert r.status_code == 200
        body = r.json()
        assert body["page"] == 2

    def test_search_min_length_ignored(self, client):
        # search < 2 caractères : pas de filtre appliqué.
        r = client.get("/api/serials", params={"search": "a"})
        assert r.status_code == 200

    def test_search_applied(self, client):
        title = uniq("ElsevierSerial")
        seed_serial(title)
        r = client.get("/api/serials", params={"search": title.lower()})
        assert r.status_code == 200
        assert any(j["title"] == title for j in r.json()["serials"])

    def test_search_with_punctuation_normalizes(self, client):
        # `.` ne figure jamais dans title_normalized (normalize_text → espace).
        # La query doit subir la même normalisation pour matcher.
        suffix = uniq("Punct").split("_")[-1]
        title = f"Rev S.A. Etudes {suffix}"
        seed_serial(title)
        r = client.get("/api/serials", params={"search": f"Rev S.A. Etudes {suffix}"})
        assert r.status_code == 200
        titles = {j["title"] for j in r.json()["serials"]}
        assert title in titles

    def test_search_finds_every_issn_of_a_serial(self, client):
        serial_id = seed_serial()
        seed_serial_issn(serial_id, issn="9990-0018", support="print")
        seed_serial_issn(serial_id, issn="9990-0026", support="electronic")
        seed_serial_issn(serial_id, issn="9990-0034", linking=True)
        seed_serial_issn(serial_id, issn="9990-0042", status="related_title")
        for term in ("9990-0018", "9990-0026", "9990-0034", "9990-0042"):
            r = client.get("/api/serials", params={"search": term, "per_page": 200})
            assert r.status_code == 200
            ids = [j["id"] for j in r.json()["serials"]]
            assert ids == [serial_id], term

    def test_search_tolerates_a_missing_hyphen_and_the_case(self, client):
        serial_id = seed_serial()
        seed_serial_issn(serial_id, issn="9990-005X", support="print")
        for term in ("9990005X", "9990-005x", "9990-005X"):
            r = client.get("/api/serials", params={"search": term, "per_page": 200})
            assert r.status_code == 200
            ids = [j["id"] for j in r.json()["serials"]]
            assert ids == [serial_id], term

    def test_search_keeps_matching_titles(self, client):
        # Un terme qui n'a pas la forme d'un ISSN ne cherche que dans les titres.
        title = uniq("TitleOnlySerial")
        serial_id = seed_serial(title)
        r = client.get("/api/serials", params={"search": title, "per_page": 200})
        assert r.status_code == 200
        assert [j["id"] for j in r.json()["serials"]] == [serial_id]

    def test_filter_by_publisher(self, client):
        publication = seed_publisher()
        j = seed_serial(publisher_id=publication)
        r = client.get("/api/serials", params={"publisher_id": publication})
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["serials"]]
        assert j in ids

    def test_filter_by_serial_type(self, client):
        jid = seed_serial()
        with owner_pool() as cur:
            cur.execute("UPDATE serials SET serial_type = 'proceedings' WHERE id = %s", (jid,))
        r = client.get("/api/serials", params={"serial_type": "proceedings", "per_page": 200})
        assert r.status_code == 200
        types = {j["serial_type"] for j in r.json()["serials"]}
        assert types == {"proceedings"}

    def test_filter_by_is_in_doaj(self, client):
        jid = seed_serial()
        with owner_pool() as cur:
            cur.execute("UPDATE serials SET is_in_doaj = TRUE WHERE id = %s", (jid,))
        r = client.get("/api/serials", params={"is_in_doaj": "true", "per_page": 200})
        assert r.status_code == 200
        flags = {j["is_in_doaj"] for j in r.json()["serials"]}
        assert flags == {True}

    def test_with_publications_excludes_orphan_serials(self, client):
        # Revue sans publi rattachée → exclue si with_publications=true.
        seed_serial("OrphanSerial")
        with_data = seed_serial("WithPubsSerial")
        _publication("p1", serial_id=with_data)
        seed_in_perimeter_contributions(with_data)
        r = client.get("/api/serials", params={"with_publications": "true", "per_page": 200})
        assert r.status_code == 200
        titles = {j["title"] for j in r.json()["serials"]}
        assert "WithPubsSerial" in titles
        assert "OrphanSerial" not in titles

    def test_with_publications_default_false_includes_orphans(self, client):
        seed_serial("OrphanDefaultSerial")
        r = client.get("/api/serials", params={"per_page": 200})
        assert r.status_code == 200
        titles = {j["title"] for j in r.json()["serials"]}
        assert "OrphanDefaultSerial" in titles

    def test_filter_by_oa_model(self, client):
        matching = seed_serial()
        other = seed_serial()
        with owner_pool() as cur:
            cur.execute("UPDATE serials SET oa_model = 'full_oa' WHERE id = %s", (matching,))
            cur.execute("UPDATE serials SET oa_model = 'subscription' WHERE id = %s", (other,))
        r = client.get("/api/serials", params={"oa_model": "full_oa", "per_page": 200})
        assert r.status_code == 200
        ids = {j["id"] for j in r.json()["serials"]}
        assert matching in ids
        assert other not in ids

    @pytest.mark.parametrize(
        "sort",
        [
            "title_asc",
            "title_desc",
            "publisher_asc",
            "publisher_desc",
            "publications_asc",
            "publications_desc",
        ],
    )
    def test_sort_variants(self, client, sort):
        # `unknown` doit fallback sur `title` ASC sans 500.
        r = client.get("/api/serials", params={"sort": sort})
        assert r.status_code == 200

    def test_per_page_above_limit_rejected(self, client):
        # `per_page` Query(le=200) → > 200 = 422.
        r = client.get("/api/serials", params={"per_page": 500})
        assert r.status_code == 422

    def test_listing_exposes_doaj_url_from_payload(self, client):
        jid = seed_serial()
        payload = {"DOAJ id": "abc123"}
        with owner_pool() as cur:
            cur.execute(
                "UPDATE serials SET doaj_payload = %s::jsonb, is_in_doaj = TRUE WHERE id = %s",
                (json.dumps(payload), jid),
            )
        r = client.get("/api/serials", params={"per_page": 200})
        assert r.status_code == 200
        mine = next(j for j in r.json()["serials"] if j["id"] == jid)
        assert mine["doaj_url"] == "https://doaj.org/toc/abc123"


def _set_issns(serial_id: int, issn: str | None, eissn: str | None = None) -> None:
    for value, support in ((issn, "print"), (eissn, "electronic")):
        if value:
            seed_serial_issn(serial_id, issn=value, support=support)


class TestSerialsWithSameTitle:
    def test_groups_serials_with_the_same_title(self, client):
        title = uniq("Doublon")
        same_title = {seed_serial(title), seed_serial(title)}
        r = client.get("/api/serials/same-titles")
        assert r.status_code == 200
        assert any({j["id"] for j in g["serials"]} == same_title for g in r.json()["groups"])

    def test_two_serials_with_their_own_issn_are_homonyms(self, client):
        title = uniq("Homonyme")
        a, b = seed_serial(title), seed_serial(title)
        _set_issns(a, "2999-2222")
        _set_issns(b, "2999-3333")
        r = client.get("/api/serials/same-titles")
        ids = {j["id"] for g in r.json()["groups"] for j in g["serials"]}
        assert not ({a, b} & ids)

    def test_titles_emptied_by_normalization_form_no_group(self, client):
        """Cas réel : un titre grec et un titre cyrillique se normalisent tous deux en chaîne vide."""
        a = seed_serial("Παιδαγωγικά ρεύματα στο Αιγαίο")
        b = seed_serial("Теория вероятностей и ее применения")
        r = client.get("/api/serials/same-titles")
        ids = {j["id"] for g in r.json()["groups"] for j in g["serials"]}
        assert not ({a, b} & ids)

    def test_count_matches_the_groups(self, client):
        groups = client.get("/api/serials/same-titles").json()["groups"]
        assert client.get("/api/serials/same-titles/count").json() == {"total": len(groups)}


class TestSerialsSharingIssn:
    def test_groups_serials_sharing_an_issn_across_supports(self, client):
        a, b = seed_serial(), seed_serial()
        _set_issns(a, "2999-1111")
        _set_issns(b, None, "2999-1111")
        r = client.get("/api/serials/shared-issns")
        assert r.status_code == 200
        groups = {g["value"]: g for g in r.json()["groups"]}
        assert {j["id"] for j in groups["2999-1111"]["serials"]} == {a, b}

    def test_count_matches_the_groups(self, client):
        groups = client.get("/api/serials/shared-issns").json()["groups"]
        assert client.get("/api/serials/shared-issns/count").json() == {"total": len(groups)}


def _seed_typed_serial_with_records(raw_types: list[tuple[str, str]]) -> int:
    """Revue typée `journal` portant un enregistrement par couple `(source, type brut)`."""
    jid = seed_serial(serial_type="journal")
    for source, raw_type in raw_types:
        _seed_record(source, serial_id=jid, raw_doc_type=raw_type)
    return jid


class TestDoiNamespaceConflicts:
    def test_enregistrement_contredit_par_l_espace_de_noms(self, client):
        """Cas réel : *Physical review. C* et son titre parasite chez OpenAlex."""
        namespace = f"10.9001/{uuid.uuid4().hex[:8]}."
        serial = seed_serial()
        parasite = seed_serial()
        seed_serial_doi_namespace(namespace, serial_id=serial, dois=40, share=0.95)
        _seed_record(serial_id=serial, doi=f"{namespace}1")
        _seed_record("openalex", serial_id=parasite, doi=f"{namespace}2")
        _seed_record("openalex", serial_id=parasite, doi=f"{namespace}3")
        # Revue posée par l'espace de noms : ni contradiction, ni témoin.
        _seed_record(
            serial_id=parasite,
            doi=f"{namespace}4",
            corrections={"serial_id": {"raw": None, "corrected_by": "X"}},
        )

        conflicts = client.get("/api/serials/doi-namespace-conflicts").json()["conflicts"]

        mine = [c for c in conflicts if c["namespace"] == namespace]
        assert len(mine) == 1
        conflict = mine[0]
        assert conflict["namespace_serial"]["id"] == serial
        assert conflict["record_serial"]["id"] == parasite
        assert (conflict["records"], conflict["sources"]) == (2, {"openalex": 2})

    def test_doi_documents_et_part_de_l_espace(self, client):
        """DOI distincts et documents de l'espace de noms ; la part des DOI est celle de l'apprentissage."""
        namespace = f"10.9001/{uuid.uuid4().hex[:8]}."
        serial = seed_serial()
        other = seed_serial()
        seed_serial_doi_namespace(namespace, serial_id=serial, dois=40, share=0.95)
        for source in ("hal", "crossref", "scanr"):
            _seed_record(source, serial_id=serial, doi=f"{namespace}1")
        _seed_record("openalex", serial_id=other, doi=f"{namespace}1")

        conflicts = client.get("/api/serials/doi-namespace-conflicts").json()["conflicts"]

        (conflict,) = [c for c in conflicts if c["namespace"] == namespace]
        assert (conflict["dois"], conflict["documents"], conflict["share"]) == (1, 4, 0.95)

    def test_count_matches_the_queue(self, client):
        conflicts = client.get("/api/serials/doi-namespace-conflicts").json()["conflicts"]
        assert client.get("/api/serials/doi-namespace-conflicts/count").json() == {
            "total": len(conflicts)
        }


class TestLikelyProceedings:
    def test_revue_d_articles_de_congres_dans_la_file(self, client):
        """Cas réel : « 2020 Winter Simulation Conference (WSC) », typée journal."""
        proceedings = _seed_typed_serial_with_records(
            [("crossref", "proceedings-article"), ("hal", "COMM"), ("hal", "ART")]
        )
        serial = _seed_typed_serial_with_records([("hal", "COMM"), ("hal", "ART")])

        items = client.get("/api/serials/likely-proceedings").json()["serials"]

        mine = {i["serial"]["id"]: i for i in items}
        assert proceedings in mine
        assert (mine[proceedings]["conference_papers"], mine[proceedings]["records"]) == (2, 3)
        assert serial not in mine

    def test_revues_sans_issn_en_tete(self, client):
        with_issn = _seed_typed_serial_with_records([("hal", "COMM")] * 5)
        _set_issns(with_issn, "2999-2222")
        without_issn = _seed_typed_serial_with_records([("hal", "COMM")])

        ids = [
            i["serial"]["id"]
            for i in client.get("/api/serials/likely-proceedings").json()["serials"]
        ]

        assert ids.index(without_issn) < ids.index(with_issn)

    def test_count_matches_the_queue(self, client):
        items = client.get("/api/serials/likely-proceedings").json()["serials"]
        assert client.get("/api/serials/likely-proceedings/count").json() == {"total": len(items)}


class TestGetSerial:
    def test_404_when_unknown(self, client):
        r = client.get("/api/serials/999999999")
        assert r.status_code == 404

    def test_returns_existing_with_detail_keys(self, client):
        title = uniq("DetailSerial")
        jid = seed_serial(title)
        r = client.get(f"/api/serials/{jid}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == jid
        assert body["title"] == title
        # Champs ajoutés par la promotion vers SerialDetailResponse.
        assert "doaj_payload" in body
        assert "doaj_imported_at" in body
        assert "publication_count" in body
        assert body["doaj_payload"] is None
        assert body["publication_count"] == 0

    def test_doaj_payload_exposed_when_present(self, client):
        jid = seed_serial()
        payload = {"License": "CC BY", "Country of publisher": "France"}
        with owner_pool() as cur:
            cur.execute(
                "UPDATE serials SET doaj_payload = %s::jsonb, is_in_doaj = TRUE WHERE id = %s",
                (json.dumps(payload), jid),
            )
        r = client.get(f"/api/serials/{jid}")
        assert r.status_code == 200
        body = r.json()
        assert body["is_in_doaj"] is True
        assert body["doaj_payload"] == payload

    def test_doaj_url_null_when_no_url_source_in_payload(self, client):
        """Payload sans `URL in DOAJ` ni `DOAJ id` → `doaj_url` reste null
        pour que le front fallback sur `<span>`."""
        jid = seed_serial()
        payload = {"License": "CC BY"}
        with owner_pool() as cur:
            cur.execute(
                "UPDATE serials SET doaj_payload = %s::jsonb, is_in_doaj = TRUE WHERE id = %s",
                (json.dumps(payload), jid),
            )
        r = client.get(f"/api/serials/{jid}")
        assert r.status_code == 200
        assert r.json()["doaj_url"] is None

    def test_doaj_url_computed_when_doaj_id_present(self, client):
        jid = seed_serial()
        payload = {"DOAJ id": "deadbeef1234"}
        with owner_pool() as cur:
            cur.execute(
                "UPDATE serials SET doaj_payload = %s::jsonb, is_in_doaj = TRUE WHERE id = %s",
                (json.dumps(payload), jid),
            )
        r = client.get(f"/api/serials/{jid}")
        assert r.status_code == 200
        assert r.json()["doaj_url"] == "https://doaj.org/toc/deadbeef1234"

    def test_doaj_url_from_csv_url_in_doaj(self, client):
        """Cas massif : payload import CSV qui porte `URL in DOAJ` (URL toute
        faite) mais pas `DOAJ id`."""
        jid = seed_serial()
        payload = {"URL in DOAJ": "https://doaj.org/toc/csvurl42"}
        with owner_pool() as cur:
            cur.execute(
                "UPDATE serials SET doaj_payload = %s::jsonb, is_in_doaj = TRUE WHERE id = %s",
                (json.dumps(payload), jid),
            )
        r = client.get(f"/api/serials/{jid}")
        assert r.status_code == 200
        assert r.json()["doaj_url"] == "https://doaj.org/toc/csvurl42"

    def test_doaj_url_prefers_csv_url_over_doaj_id(self, client):
        jid = seed_serial()
        payload = {"URL in DOAJ": "https://doaj.org/toc/fromcsv", "DOAJ id": "fromid"}
        with owner_pool() as cur:
            cur.execute(
                "UPDATE serials SET doaj_payload = %s::jsonb, is_in_doaj = TRUE WHERE id = %s",
                (json.dumps(payload), jid),
            )
        r = client.get(f"/api/serials/{jid}")
        assert r.status_code == 200
        assert r.json()["doaj_url"] == "https://doaj.org/toc/fromcsv"


class TestSerialDashboard:
    def test_404_when_unknown(self, client):
        r = client.get("/api/serials/999999999/dashboard")
        assert r.status_code == 404

    def test_returns_distributions_for_serial_without_publications(self, client):
        jid = seed_serial()
        # Type explicite : le défaut DB est désormais 'unknown' (pas de mapping
        # doc_types) ; on teste ici le mapping d'un 'journal'.
        with owner_pool() as cur:
            cur.execute("UPDATE serials SET serial_type = 'journal' WHERE id = %s", (jid,))
        r = client.get(f"/api/serials/{jid}/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert body["total_publications"] == 0
        assert body["doc_types"] == []
        assert body["oa_statuses"] == []
        # `expected_doc_types` non vide (serial_type='journal' a un mapping),
        # `expected_oa_statuses` vide (oa_model NULL = pas de mapping).
        assert "article" in body["expected_doc_types"]
        assert body["expected_oa_statuses"] == []

    def test_aggregates_publications(self, client):
        jid = seed_serial()
        _publication("p1", doc_type="article", oa_status="gold", serial_id=jid)
        _publication("p2", doc_type="article", oa_status="closed", serial_id=jid)
        _publication("p3", doc_type="preprint", oa_status=None, serial_id=jid)
        seed_in_perimeter_contributions(jid)
        r = client.get(f"/api/serials/{jid}/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert body["total_publications"] == 3
        dt = {(d["doc_type"], d["count"]) for d in body["doc_types"]}
        assert dt == {("article", 2), ("preprint", 1)}
        oa = {(o["oa_status"], o["count"]) for o in body["oa_statuses"]}
        assert oa == {("gold", 1), ("closed", 1), (None, 1)}

    def test_expected_flags_doc_types_against_serial_type(self, client):
        jid = seed_serial()
        with owner_pool() as cur:
            # `serial_type=proceedings` : article inattendu, conference_paper attendu.
            cur.execute("UPDATE serials SET serial_type = 'proceedings' WHERE id = %s", (jid,))
            _publication("p1", doc_type="article", serial_id=jid)
            _publication("p2", doc_type="conference_paper", serial_id=jid)
        seed_in_perimeter_contributions(jid)
        r = client.get(f"/api/serials/{jid}/dashboard")
        body = r.json()
        by_dt = {d["doc_type"]: d for d in body["doc_types"]}
        assert by_dt["article"]["expected"] is False
        assert by_dt["conference_paper"]["expected"] is True
        assert body["expected_doc_types"] == sorted(["conference", "conference_paper", "other"])

    def test_expected_flags_oa_statuses_against_oa_model(self, client):
        jid = seed_serial()
        with owner_pool() as cur:
            cur.execute("UPDATE serials SET oa_model = 'subscription' WHERE id = %s", (jid,))
            _publication("p1", oa_status="closed", serial_id=jid)
            _publication("p2", oa_status="gold", serial_id=jid)
            _publication("p3", oa_status="unknown", serial_id=jid)
        seed_in_perimeter_contributions(jid)
        r = client.get(f"/api/serials/{jid}/dashboard")
        body = r.json()
        by_oa = {o["oa_status"]: o for o in body["oa_statuses"]}
        assert by_oa["closed"]["expected"] is True
        assert by_oa["gold"]["expected"] is False
        # `unknown` reste expected (pas de signal).
        assert by_oa["unknown"]["expected"] is True
        assert set(body["expected_oa_statuses"]) == {"closed", "green", "hybrid", "bronze"}

    def test_no_oa_model_yields_empty_expected_list(self, client):
        # oa_model NULL → pas de signal côté revue → expected_oa_statuses vide,
        # tous les counts retournent expected=True.
        jid = seed_serial()
        _publication("p1", oa_status="gold", serial_id=jid)
        _publication("p2", oa_status="closed", serial_id=jid)
        seed_in_perimeter_contributions(jid)
        r = client.get(f"/api/serials/{jid}/dashboard")
        body = r.json()
        assert body["expected_oa_statuses"] == []
        assert all(o["expected"] is True for o in body["oa_statuses"])


class TestSerialSubjects:
    def test_returns_empty_for_serial_without_publications(self, client):
        jid = seed_serial()
        r = client.get(f"/api/serials/{jid}/subjects")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_top_subjects_excluding_generic(self, client):
        jid = seed_serial()
        publication_ids = [_publication("p1", serial_id=jid), _publication("p2", serial_id=jid)]
        # Sujet spécifique (sous le seuil 5000) attaché aux 2 publis.
        specific_label = uniq("specific_subject")
        spec_id = seed_subject(specific_label, usage_count=100)
        # Sujet trop générique (au-dessus du seuil) attaché à 1 publi —
        # doit être exclu du top.
        generic_label = uniq("generic_subject")
        gen_id = seed_subject(generic_label, usage_count=9999)
        for publication_id, subject_id in (
            (publication_ids[0], spec_id),
            (publication_ids[1], spec_id),
            (publication_ids[0], gen_id),
        ):
            seed_publication_subject(publication_id, subject_id=subject_id)
        seed_in_perimeter_contributions(jid)
        r = client.get(f"/api/serials/{jid}/subjects")
        assert r.status_code == 200
        body = r.json()
        labels = {s["label"] for s in body}
        assert specific_label in labels
        assert generic_label not in labels
        spec_entry = next(s for s in body if s["label"] == specific_label)
        assert spec_entry["count"] == 2

    def test_respects_limit(self, client):
        jid = seed_serial()
        r = client.get(f"/api/serials/{jid}/subjects", params={"limit": 5})
        assert r.status_code == 200
        # Tableau vide pour ce jid neuf ; on vérifie surtout que limit=5 est accepté.
        assert r.json() == []

    def test_limit_above_max_rejected(self, client):
        jid = seed_serial()
        r = client.get(f"/api/serials/{jid}/subjects", params={"limit": 500})
        assert r.status_code == 422


class TestUpdateSerial:
    def test_updates_partial_fields(self, auth_client):
        jid = seed_serial()
        r = auth_client.put(
            f"/api/serials/{jid}",
            json={
                "title": "UpdatedTitle",
                "is_academic": False,
            },
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        # Vérifier en base que seuls les champs envoyés sont écrits.
        with owner_pool() as cur:
            cur.execute("SELECT title, is_academic FROM serials WHERE id = %s", (jid,))
            row = cur.fetchone()
            assert row["title"] == "UpdatedTitle"
            assert row["is_academic"] is False


class TestTypeChangeImpact:
    def test_counts_without_writing(self, auth_client):
        """L'aperçu écrit dans un SAVEPOINT annulé : le type de la revue ne bouge pas."""
        jid = seed_serial()
        auth_client.put(f"/api/serials/{jid}", json={"serial_type": "journal"})
        r = auth_client.post(
            f"/api/serials/{jid}/type-change-impact", json={"serial_type": "proceedings"}
        )
        assert r.status_code == 200
        assert "count" in r.json()
        with owner_pool() as cur:
            cur.execute("SELECT serial_type FROM serials WHERE id = %s", (jid,))
            assert cur.fetchone()["serial_type"] == "journal"

    def test_404_on_unknown_serial(self, auth_client):
        """L'aperçu emprunte le chemin de l'édition : il en hérite l'absence."""
        r = auth_client.post(
            "/api/serials/999999/type-change-impact", json={"serial_type": "proceedings"}
        )
        assert r.status_code == 404


class TestMergeSerials:
    def test_404_when_target_missing(self, auth_client):
        src = seed_serial()
        r = auth_client.post("/api/serials/999999999/merge", json={"source_id": src})
        assert r.status_code == 404
        assert "introuvable" in r.json()["detail"]

    def test_404_when_source_missing(self, auth_client):
        dst = seed_serial()
        r = auth_client.post(f"/api/serials/{dst}/merge", json={"source_id": 999999998})
        assert r.status_code == 404
        assert "introuvable" in r.json()["detail"]

    def test_happy_path(self, auth_client):
        src = seed_serial("MergeSrc")
        dst = seed_serial("MergeDst")
        r = auth_client.post(f"/api/serials/{dst}/merge", json={"source_id": src})
        assert r.status_code == 200
        body = r.json()
        assert body == {"merged": True, "source_id": src, "target_id": dst}
        # Source supprimée, target conservée.
        with owner_pool() as cur:
            cur.execute("SELECT id FROM serials WHERE id IN (%s, %s)", (src, dst))
            ids = {row["id"] for row in cur.fetchall()}
            assert dst in ids
            assert src not in ids


# ── GET /api/serials/oa-models ─────────────────────────────────


class TestOaModels:
    def test_returns_enum_with_fr_labels(self, client):
        r = client.get("/api/serials/oa-models")
        assert r.status_code == 200
        models = r.json()
        # Source de vérité = domain.serials.journal.OA_MODELS / OA_MODEL_LABELS_FR.
        values = [m["value"] for m in models]
        assert values == ["subscription", "full_oa", "diamond", "repository"]
        assert all("label_fr" in m and m["label_fr"] for m in models)


# ── GET /api/serials/types ─────────────────────────────────────


class TestSerialTypes:
    def test_returns_all_values_with_labels(self, client):
        r = client.get("/api/serials/types")
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
            "unknown",
        ]
        assert all("label_fr" in opt and opt["label_fr"] for opt in body)


class TestSerialsFacets:
    def test_returns_every_facet(self, client):
        r = client.get("/api/serials/facets")
        assert r.status_code == 200
        body = r.json()
        assert {"serial_types", "oa_models", "doaj"} <= set(body)

    def test_honours_search_and_publisher(self, client):
        r = client.get("/api/serials/facets", params={"search": "nature", "publisher_id": 1})
        assert r.status_code == 200

    def test_honours_the_other_dimensions(self, client):
        r = client.get(
            "/api/serials/facets",
            params={
                "serial_type": "journal,proceedings",
                "oa_model": "full_oa",
                "is_in_doaj": "true",
                "with_publications": "true",
            },
        )
        assert r.status_code == 200


class TestSerialsPublisherFacet:
    """GET /api/serials/facets/entities : facette éditeur, décomptée en revues."""

    def test_counts_serials_per_publisher(self, client):
        name = uniq("FacetPublisher")
        publisher_id = seed_publisher(name)
        seed_serial(publisher_id=publisher_id)
        seed_serial(publisher_id=publisher_id)
        r = client.get(
            "/api/serials/facets/entities",
            params={"kind": "publisher", "entity_search": name},
        )
        assert r.status_code == 200
        counts = {e["id"]: e["count"] for e in r.json()["entities"]}
        assert counts == {publisher_id: 2}

    def test_entity_search_filters_on_the_publisher_name(self, client):
        name = uniq("Searchable")
        wanted = seed_publisher(name)
        other = seed_publisher(uniq("Autre"))
        seed_serial(publisher_id=wanted)
        seed_serial(publisher_id=other)
        r = client.get(
            "/api/serials/facets/entities",
            params={"kind": "publisher", "entity_search": name},
        )
        assert r.status_code == 200
        ids = {e["id"] for e in r.json()["entities"]}
        assert ids == {wanted}

    def test_ignores_the_publisher_filter_but_honours_the_others(self, client):
        # La facette écarte sa propre dimension : un éditeur sélectionné ne réduit pas les options.
        selected = seed_publisher(uniq("Selected"))
        other = seed_publisher(uniq("Other"))
        seed_serial(publisher_id=selected)
        proceedings = seed_serial(publisher_id=other)
        with owner_pool() as cur:
            cur.execute(
                "UPDATE serials SET serial_type = 'proceedings' WHERE id = %s", (proceedings,)
            )
        r = client.get(
            "/api/serials/facets/entities",
            params={"kind": "publisher", "publisher_id": selected, "serial_type": "proceedings"},
        )
        assert r.status_code == 200
        ids = {e["id"] for e in r.json()["entities"]}
        assert other in ids
        assert selected not in ids

    def test_rejects_an_unsupported_kind(self, client):
        r = client.get("/api/serials/facets/entities", params={"kind": "serial"})
        assert r.status_code == 422


# ── Traçabilité des écritures sur les revues ─────────────────


class TestTracabiliteEdition:
    """La requalification consécutive à un changement de type était consignée, l'édition qui la déclenche non.

    Un changement d'ISSN ou de titre ne requalifie rien et ne laissait donc aucune trace, alors qu'il commande le rapprochement des publications avec leur revue.
    """

    def test_la_modification_ne_consigne_que_les_champs_fournis(self, auth_client):
        jid = seed_serial(uniq("Audit revue"))

        issns = [{"issn": "1234-5679", "support": "print"}]
        r = auth_client.put(f"/api/serials/{jid}", json={"issns": issns})
        assert r.status_code == 200, r.text

        with owner_pool() as cur:
            cur.execute(
                "SELECT payload, user_id FROM audit_log "
                "WHERE event_type = 'serial.updated' AND aggregate_id = %s ORDER BY id",
                (jid,),
            )
            evenements = cur.fetchall()

        assert len(evenements) == 1
        assert evenements[0]["payload"] == {"issns": issns}
        assert evenements[0]["user_id"]
