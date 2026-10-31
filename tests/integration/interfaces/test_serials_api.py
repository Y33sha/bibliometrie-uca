"""Tests d'intégration du router des revues (`interfaces.api.routers.serials`).

Couvre :
- GET /api/serials (liste, recherche par titre et ISSN, filtre par éditeur, tris)
- GET /api/serials/facets/entities (facette des éditeurs)
- les files de contrôle : titres identiques, ISSN partagés, conflits d'espace de noms DOI, recueils d'actes probables
- GET /api/serials/{id} (fiche avec DOAJ, 404)
- GET /api/serials/{id}/subjects (sujets principaux, hors sujets génériques)
- PUT /api/serials/{id} (mise à jour, authentification requise, 404) et l'aperçu d'un changement de type
- POST /api/serials/{id}/merge (authentification requise, 404 sur la cible ou la source, fusion)
- GET /api/serials/oa-models et /api/serials/types
- la trace d'audit des modifications
"""

from __future__ import annotations

import json
import uuid
from functools import partial

import pytest

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
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


def _derived_doi(doi: str) -> list[SourceIdentifier]:
    """Construit le DOI `derived` d'un agrégateur : celui de la localisation principale chez OpenAlex, de l'identifiant chez ScanR."""
    return [SourceIdentifier(SourceIdentifierType.DOI, doi, SourceIdentifierRole.DERIVED)]


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
        # Une recherche de moins de deux caractères est ignorée.
        r = client.get("/api/serials", params={"search": "a"})
        assert r.status_code == 200

    def test_search_applied(self, client):
        title = uniq("ElsevierSerial")
        seed_serial(title)
        r = client.get("/api/serials", params={"search": title.lower()})
        assert r.status_code == 200
        assert any(j["title"] == title for j in r.json()["serials"])

    def test_search_with_punctuation_normalizes(self, client):
        # `normalize_text` change `.` en espace dans `title_normalized` ; la recherche subit la même normalisation.
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
        seed_serial_issn(serial_id, issn="9990-0034", issnl="9990-0034")
        seed_serial_issn(serial_id, issn="9990-0042", status="cancelled")
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
        # Un terme sans la forme d'un ISSN cherche seulement dans les titres.
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

    def _seed_with_and_without_publications(self) -> None:
        seed_serial("OrphanSerial")
        with_data = seed_serial("WithPubsSerial")
        _publication("p1", serial_id=with_data)
        seed_in_perimeter_contributions(with_data)

    def _titles(self, client, **params) -> set[str]:
        r = client.get("/api/serials", params={"per_page": 200, **params})
        assert r.status_code == 200
        return {j["title"] for j in r.json()["serials"]}

    def test_has_publications_true_excludes_orphans(self, client):
        self._seed_with_and_without_publications()
        titles = self._titles(client, has_publications="true")
        assert "WithPubsSerial" in titles
        assert "OrphanSerial" not in titles

    def test_has_publications_false_keeps_orphans_only(self, client):
        self._seed_with_and_without_publications()
        titles = self._titles(client, has_publications="false")
        assert "OrphanSerial" in titles
        assert "WithPubsSerial" not in titles

    def test_has_publications_absent_lists_all(self, client):
        self._seed_with_and_without_publications()
        assert {"OrphanSerial", "WithPubsSerial"} <= self._titles(client)

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
        r = client.get("/api/serials", params={"sort": sort})
        assert r.status_code == 200

    def test_per_page_above_limit_rejected(self, client):
        # `per_page` au-delà de 200 : 422.
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
        """Un titre grec et un titre cyrillique, tous deux normalisés en chaîne vide, ne forment pas de groupe."""
        a = seed_serial("Παιδαγωγικά ρεύματα στο Αιγαίο")
        b = seed_serial("Теория вероятностей и ее применения")
        r = client.get("/api/serials/same-titles")
        ids = {j["id"] for g in r.json()["groups"] for j in g["serials"]}
        assert not ({a, b} & ids)

    def test_count_matches_the_groups(self, client):
        groups = client.get("/api/serials/same-titles").json()["groups"]
        assert client.get("/api/serials/same-titles/count").json() == {"total": len(groups)}


def _seed_typed_serial_with_records(raw_types: list[tuple[str, str]]) -> int:
    """Sème une revue typée `journal`, avec un enregistrement source par couple `(source, type brut)`."""
    jid = seed_serial(serial_type="journal")
    for source, raw_type in raw_types:
        _seed_record(source, serial_id=jid, raw_doc_type=raw_type)
    return jid


class TestDoiNamespaceConflicts:
    def test_enregistrement_contredit_par_l_espace_de_noms(self, client):
        """Les enregistrements sources OpenAlex d'une revue parasite, aux DOI de l'espace de noms d'une autre revue, forment un conflit (cas de *Physical review. C*)."""
        namespace = f"10.9001/{uuid.uuid4().hex[:8]}."
        serial = seed_serial()
        parasite = seed_serial()
        seed_serial_doi_namespace(namespace, serial_id=serial, dois=40, share=0.95)
        _seed_record(serial_id=serial, doi=f"{namespace}1")
        _seed_record("openalex", serial_id=parasite, identifiers=_derived_doi(f"{namespace}2"))
        _seed_record("openalex", serial_id=parasite, identifiers=_derived_doi(f"{namespace}3"))
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
        """Le conflit compte les DOI distincts et les enregistrements sources de l'espace de noms (`documents`) ; la part des DOI est celle de l'apprentissage."""
        namespace = f"10.9001/{uuid.uuid4().hex[:8]}."
        serial = seed_serial()
        other = seed_serial()
        seed_serial_doi_namespace(namespace, serial_id=serial, dois=40, share=0.95)
        for source in ("hal", "crossref"):
            _seed_record(source, serial_id=serial, doi=f"{namespace}1")
        _seed_record("scanr", serial_id=serial, identifiers=_derived_doi(f"{namespace}1"))
        _seed_record("openalex", serial_id=other, identifiers=_derived_doi(f"{namespace}1"))

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
        """Une revue typée `journal` aux enregistrements sources de congrès entre dans la file, comme « 2020 Winter Simulation Conference (WSC) »."""
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
        _set_issns(with_issn, "2999-6665")
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
        # Champs propres à la fiche détaillée.
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
        """Sans `URL in DOAJ` ni `DOAJ id` dans le payload, `doaj_url` est nul : l'interface affiche le DOAJ sans lien."""
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
        """`doaj_url` reprend l'URL complète `URL in DOAJ` d'un payload d'import CSV sans `DOAJ id`, le cas le plus fréquent."""
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


class TestSerialSubjects:
    def test_returns_empty_for_serial_without_publications(self, client):
        jid = seed_serial()
        r = client.get(f"/api/serials/{jid}/subjects")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_top_subjects_excluding_generic(self, client):
        jid = seed_serial()
        publication_ids = [_publication("p1", serial_id=jid), _publication("p2", serial_id=jid)]
        # Sujet spécifique, sous le seuil de généricité (5000), attaché aux deux publications.
        specific_label = uniq("specific_subject")
        spec_id = seed_subject(specific_label, usage_count=100)
        # Sujet générique, au-dessus du seuil, attaché à une publication : exclu des sujets principaux.
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
        # Revue sans publication : la liste est vide, et `limit=5` est accepté.
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
        # Les champs envoyés sont écrits en base.
        with owner_pool() as cur:
            cur.execute("SELECT title, is_academic FROM serials WHERE id = %s", (jid,))
            row = cur.fetchone()
            assert row["title"] == "UpdatedTitle"
            assert row["is_academic"] is False


class TestTypeChangeImpact:
    def test_counts_without_writing(self, auth_client):
        """L'aperçu écrit dans un SAVEPOINT annulé : le type de la revue reste inchangé."""
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

    def test_corrections_with_identifiers_are_counted(self, auth_client):
        """La correction unaire rejouée par l'aperçu écrit les statuts des identifiants, sous le rôle de l'API."""
        jid = seed_serial(serial_type="journal")
        publication_id = _publication(doc_type="article", serial_id=jid)
        _seed_record(
            publication_id=publication_id,
            serial_id=jid,
            doc_type="article",
            doi=f"10.1/{uniq('x')}",
        )
        r = auth_client.post(
            f"/api/serials/{jid}/type-change-impact", json={"serial_type": "media"}
        )
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_404_on_unknown_serial(self, auth_client):
        """L'aperçu suit le chemin de l'édition : une revue inconnue renvoie 404."""
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
        # Revue source supprimée, cible conservée.
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
        # Référence : `OA_MODELS` et `OA_MODEL_LABELS_FR` de `domain.serials.journal`.
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
            "data_journal",
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
        assert {"serial_types", "oa_models", "doaj", "publications"} <= set(body)

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
                "has_publications": "true",
            },
        )
        assert r.status_code == 200

    def test_publications_counts_ignore_their_own_filter(self, client):
        publisher = seed_publisher()
        seed_serial(publisher_id=publisher)
        with_data = seed_serial(publisher_id=publisher)
        _publication("p1", serial_id=with_data)
        seed_in_perimeter_contributions(with_data)
        r = client.get(
            "/api/serials/facets", params={"publisher_id": publisher, "has_publications": "true"}
        )
        assert r.status_code == 200
        assert r.json()["publications"] == {"yes": 1, "no": 1}


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
    """L'édition d'une revue est consignée, y compris un changement de titre : il commande le rattachement des publications à leur revue."""

    def test_la_modification_ne_consigne_que_les_champs_fournis(self, auth_client):
        jid = seed_serial(uniq("Audit revue"))

        r = auth_client.put(f"/api/serials/{jid}", json={"title": "Audit revue renommée"})
        assert r.status_code == 200, r.text

        with owner_pool() as cur:
            cur.execute(
                "SELECT payload, user_id FROM audit_log "
                "WHERE event_type = 'serial.updated' AND entity_id = %s ORDER BY id",
                (jid,),
            )
            evenements = cur.fetchall()

        assert len(evenements) == 1
        assert evenements[0]["payload"] == {"title": "Audit revue renommée"}
        assert evenements[0]["user_id"]
