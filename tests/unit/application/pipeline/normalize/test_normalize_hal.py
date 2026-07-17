"""Tests unitaires de `application.pipeline.normalize.normalize_hal`.

Couvre les helpers (as_str, get_title, upsert_journal, extract_pub_metadata), `insert_hal_document` (collections, biblio, keywords, NNT, topics), le parsing TEI (`parse_tei_author_identifiers`), `parse_author_structures` (format `_FacetSep_`/`_JoinSep_`), le parsing auteurs `build_hal_author_records` (composite + TEI), l'orchestrateur `process_work` (métadonnées minimales, happy path), et la classe `HalNormalizer` (preload, délégation).

Pattern : `_FakeQueries` + `_FakeAuthorshipQueries` + `MagicMock`, pas de DB.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from application.pipeline.normalize import normalize_hal
from application.pipeline.normalize.normalize_hal import (
    HalNormalizer,
    active_embargo_until,
    as_str,
    build_hal_author_records,
    extract_pub_metadata,
    get_title,
    insert_hal_document,
    parse_author_structures,
    process_work,
    upsert_journal,
    upsert_publisher,
)
from application.ports.pipeline.normalize.source_publications import SourcePublicationRow
from application.ports.pipeline.normalize.staging import StagingRow

# ── Stubs ────────────────────────────────────────────────────────


def _staging_row(staging_id=1, hal_id="hal-1", doi=None, raw=None):
    return StagingRow(
        id=staging_id,
        source_id=hal_id,
        doi=doi,
        raw_data=raw or {},
    )


class _FakeQueries:
    def __init__(self) -> None:
        self.upserted_documents: list[SourcePublicationRow] = []

    def upsert_source_publication(self, conn, row) -> int:
        self.upserted_documents.append(row)
        return 999


class _FakeAuthorshipQueries:
    """Stub du port batch partagé — enregistre les appels du writer."""

    def __init__(self) -> None:
        self.cleared_for: list[int] = []

    def clear_source_authorships_for_publication(self, conn, source_publication_id: int) -> None:
        self.cleared_for.append(source_publication_id)

    def upsert_source_authorships_batch(self, conn, values) -> None: ...

    def fetch_source_authorship_ids_by_position(self, conn, **kw) -> dict[int, int]:
        return {}

    def upsert_addresses_batch(self, conn, values) -> None: ...

    def fetch_address_ids_by_raw_text(self, conn, raw_texts) -> dict[str, int]:
        return {}

    def apply_address_countries_batch(self, conn, values) -> None: ...

    def apply_address_suggested_countries_batch(self, conn, values) -> None: ...

    def insert_source_authorship_addresses_batch(self, conn, values) -> None: ...


class _FakeStagingQueries:
    def __init__(self) -> None:
        self.marked_done: list[int] = []

    def mark_done(self, conn, staging_id: int) -> None:
        self.marked_done.append(staging_id)


# ── as_str ───────────────────────────────────────────────────────


class TestAsStr:
    def test_none(self):
        assert as_str(None) is None

    def test_empty_list(self):
        assert as_str([]) is None

    def test_list_first(self):
        assert as_str(["a", "b"]) == "a"

    def test_string_passthrough(self):
        assert as_str("hello") == "hello"

    def test_non_str_coerced(self):
        assert as_str(42) == "42"


# ── get_title ────────────────────────────────────────────────────


class TestGetTitle:
    def test_title_as_list(self):
        assert get_title({"title_s": ["My Title"]}) == "My Title"

    def test_title_as_string(self):
        assert get_title({"title_s": "Plain"}) == "Plain"

    def test_fallback_to_label(self):
        assert get_title({"label_s": "Fallback"}) == "Fallback"

    def test_empty(self):
        assert get_title({}) == ""

    def test_empty_title_list_falls_back_to_label(self):
        assert get_title({"title_s": [], "label_s": "L"}) == "L"


# ── upsert_publisher / upsert_journal ────────────────────────────


class TestUpsertJournal:
    def test_no_title_returns_none(self):
        assert upsert_journal({}, None, journal_repo=MagicMock()) is None

    def test_happy_path(self, monkeypatch):
        captured: dict[str, Any] = {}

        def fake_create(title, *, issn, eissn, publisher_id, repo):
            captured.update(title=title, issn=issn, eissn=eissn, publisher_id=publisher_id)
            return 7

        monkeypatch.setattr(normalize_hal, "find_or_create_journal", fake_create)
        result = upsert_journal(
            {
                "journalTitle_s": "Nature",
                "journalIssn_s": "1234-5678",
                "journalEissn_s": "2345-6789",
            },
            42,
            journal_repo=MagicMock(),
        )
        assert result == 7
        assert captured == {
            "title": "Nature",
            "issn": "1234-5678",
            "eissn": "2345-6789",
            "publisher_id": 42,
        }


class TestUpsertPublisher:
    def test_delegates_to_service(self, monkeypatch):
        captured: dict[str, Any] = {}

        def fake_find(name, *, repo):
            captured["name"] = name
            return 5

        monkeypatch.setattr(normalize_hal, "find_or_create_publisher", fake_find)
        result = upsert_publisher("Elsevier", publisher_repo=MagicMock())
        assert result == 5
        assert captured["name"] == "Elsevier"


# ── extract_pub_metadata ─────────────────────────────────────────


class TestExtractPubMetadata:
    def test_minimal(self):
        meta = extract_pub_metadata({"title_s": ["T"], "producedDateY_i": 2024}, journal_id=42)
        assert meta["title"] == "T"
        assert meta["pub_year"] == 2024
        assert meta["journal_id"] == 42
        # Pas de container_title si journal_id présent.
        assert meta["container_title"] is None

    def test_book_title_fallback_when_no_journal(self):
        meta = extract_pub_metadata({"bookTitle_s": "Book"}, journal_id=None)
        assert meta["container_title"] == "Book"

    def test_conference_title_fallback(self):
        meta = extract_pub_metadata({"conferenceTitle_s": "Conf"}, journal_id=None)
        assert meta["container_title"] == "Conf"

    def test_language_from_list(self):
        meta = extract_pub_metadata({"language_s": ["fr", "en"]}, journal_id=None)
        assert meta["language"] == "fr"

    def test_no_language(self):
        meta = extract_pub_metadata({}, journal_id=None)
        assert meta["language"] is None

    def test_nnt_normalized(self):
        meta = extract_pub_metadata({"nntId_s": "  2024CLFAC001  "}, journal_id=None)
        assert meta["nnt"] == "2024CLFAC001"


# ── active_embargo_until ─────────────────────────────────────────


def _embargo_tei(refs: str) -> str:
    return f'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>{refs}</body></text></TEI>'


class TestActiveEmbargoUntil:
    TODAY = date(2026, 6, 20)

    def test_future_file_embargo_returned(self):
        xml = _embargo_tei('<ref type="file" target="x"><date notBefore="2027-01-01"/></ref>')
        assert active_embargo_until(xml, self.TODAY) == date(2027, 1, 1)

    def test_past_embargo_is_none(self):
        # Date échue : pas d'embargo actif (fichier accessible).
        xml = _embargo_tei('<ref type="file" target="x"><date notBefore="2018-09-14"/></ref>')
        assert active_embargo_until(xml, self.TODAY) is None

    def test_multiple_files_take_latest(self):
        xml = _embargo_tei(
            '<ref type="file" target="a"><date notBefore="2026-12-01"/></ref>'
            '<ref type="file" target="b"><date notBefore="2027-03-01"/></ref>'
        )
        assert active_embargo_until(xml, self.TODAY) == date(2027, 3, 1)

    def test_non_file_ref_ignored(self):
        # Embargo sur une annexe (type='annex') : ignoré, seul le fichier compte.
        xml = _embargo_tei('<ref type="annex" target="x"><date notBefore="2027-01-01"/></ref>')
        assert active_embargo_until(xml, self.TODAY) is None

    def test_file_ref_without_date_is_none(self):
        assert (
            active_embargo_until(_embargo_tei('<ref type="file" target="x"/>'), self.TODAY) is None
        )

    def test_no_label_xml(self):
        assert active_embargo_until(None, self.TODAY) is None
        assert active_embargo_until("", self.TODAY) is None

    def test_malformed_xml_is_none(self):
        assert active_embargo_until("<not valid xml", self.TODAY) is None


# ── insert_hal_document ──────────────────────────────────────────


class TestInsertHalDocument:
    def _call(self, queries, doc, *, pub_meta=None) -> dict:
        # Par défaut, pub_meta est dérivé via extract_pub_metadata pour rester
        # cohérent avec le flux réel (extract → insert). Tests qui veulent
        # forcer une valeur passent un pub_meta explicite.
        if pub_meta is None:
            pub_meta = extract_pub_metadata(doc, journal_id=None)
        insert_hal_document(
            MagicMock(),
            queries,
            doc,
            staging_id=1,
            hal_id="h1",
            pub_meta=pub_meta,
        )
        return queries.upserted_documents[-1]

    def test_collections_from_coll_codes(self):
        queries = _FakeQueries()
        captured = self._call(queries, {"collCode_s": ["UCA", "LIMOS", "UCA"]})
        # Dédupliquées, triées, depuis le seul `collCode_s` du raw_data.
        assert captured.hal_collections == ["LIMOS", "UCA"]

    def test_no_collections_returns_none(self):
        queries = _FakeQueries()
        captured = self._call(queries, {})
        assert captured.hal_collections is None

    def test_doc_type_concatenated_with_subtype(self):
        queries = _FakeQueries()
        captured = self._call(queries, {"docType_s": "ART", "docSubType_s": "review"})
        assert captured.doc_type == "ART_review"

    def test_doc_type_no_subtype(self):
        queries = _FakeQueries()
        captured = self._call(queries, {"docType_s": "BOOK"})
        assert captured.doc_type == "BOOK"

    def test_nnt_goes_in_external_ids(self):
        queries = _FakeQueries()
        captured = self._call(queries, {"nntId_s": "2024CLFAC001"})
        assert captured.external_ids == {"hal_id": ["h1"], "nnt": "2024CLFAC001"}

    def test_hal_id_always_in_external_ids(self):
        """Le normalizer pose `external_ids.hal_id = source_id` même hors thèse, pour que `hal_id` soit un token de confirmation et que HAL soit clusterisé comme les autres sources (symétrie avec ce que theses fait déjà pour NNT)."""
        queries = _FakeQueries()
        captured = self._call(queries, {})
        assert captured.external_ids == {"hal_id": ["h1"]}

    def test_keywords_deduplicated(self):
        queries = _FakeQueries()
        captured = self._call(queries, {"keyword_s": ["a", "b", "a", "c"]})
        assert captured.keywords == ["a", "b", "c"]

    def test_keywords_empty(self):
        queries = _FakeQueries()
        captured = self._call(queries, {"keyword_s": []})
        assert captured.keywords is None

    def test_topics_from_domain(self):
        """Les domaines sont stockés tels que la source les expose ; la découpe en libellés vit dans la phase `subjects`."""
        queries = _FakeQueries()
        entries = [
            "sdv.bibs_FacetSep_Sciences du Vivant [q-bio]/Biostatistiques",
            "info.algo_FacetSep_Informatique [cs]/Algorithme et structure de données",
        ]
        captured = self._call(queries, {"fr_domainAllCodeLabel_fs": entries})
        assert captured.topics == {"hal_domains": entries}

    def test_biblio_built_from_volume_issue_pages(self):
        queries = _FakeQueries()
        captured = self._call(queries, {"volume_s": "10", "issue_s": "2", "page_s": "100-120"})
        assert captured.biblio == {"volume": "10", "issue": "2", "pages": "100-120"}

    def test_biblio_empty(self):
        queries = _FakeQueries()
        captured = self._call(queries, {})
        assert captured.biblio is None

    def test_biblio_publisher_from_journalPublisher_s(self):
        queries = _FakeQueries()
        captured = self._call(queries, {"journalPublisher_s": "Elsevier"})
        assert captured.biblio == {"publisher": "Elsevier"}

    def test_biblio_publisher_fallback_to_publisher_s(self):
        queries = _FakeQueries()
        captured = self._call(queries, {"publisher_s": "Springer"})
        assert captured.biblio == {"publisher": "Springer"}

    def test_biblio_journalPublisher_s_wins_over_publisher_s(self):
        queries = _FakeQueries()
        captured = self._call(
            queries, {"journalPublisher_s": "Elsevier", "publisher_s": "Springer"}
        )
        assert captured.biblio == {"publisher": "Elsevier"}

    def test_biblio_journal_built_from_title_issn_eissn(self):
        queries = _FakeQueries()
        captured = self._call(
            queries,
            {
                "journalTitle_s": "J. Phys.",
                "journalIssn_s": "0022-3727",
                "journalEissn_s": "1361-6463",
            },
        )
        assert captured.biblio == {
            "journal": {
                "title": "J. Phys.",
                "issn": "0022-3727",
                "eissn": "1361-6463",
            }
        }

    def test_biblio_journal_partial(self):
        queries = _FakeQueries()
        captured = self._call(queries, {"journalTitle_s": "J. Phys."})
        assert captured.biblio == {"journal": {"title": "J. Phys."}}

    def test_url_from_uri(self):
        queries = _FakeQueries()
        captured = self._call(queries, {"uri_s": "https://hal.science/hal-123"})
        assert captured.urls == ["https://hal.science/hal-123"]

    def test_pub_meta_propagates_journal_oa_lang(self):
        queries = _FakeQueries()
        captured = self._call(
            queries,
            {},
            pub_meta={
                "doi": None,
                "title": None,
                "pub_year": None,
                "doc_type": None,
                "nnt": None,
                "journal_id": 7,
                "oa_status": "gold",
                "embargo_until": date(2027, 1, 1),
                "language": "fr",
                "container_title": "Book",
            },
        )
        assert captured.journal_id == 7
        assert captured.oa_status == "gold"
        assert captured.embargo_until == date(2027, 1, 1)
        assert captured.language == "fr"
        assert captured.container_title == "Book"


# `parse_tei_author_identifiers` est testé dans
# `tests/unit/application/test_parse_tei_author_identifiers.py` — pas de duplication ici.


# ── parse_author_structures ──────────────────────────────────────


class TestParseAuthorStructures:
    def test_no_entries(self):
        assert parse_author_structures({}) == {}

    def test_basic_parse(self):
        doc = {
            "authIdHasPrimaryStructure_fs": [
                "49236-749496_FacetSep_Dupont, Marie_JoinSep_300012_FacetSep_LIMOS"
            ]
        }
        struct_names: dict[str, str] = {}
        result = parse_author_structures(doc, struct_name_by_hal_id=struct_names)
        assert result == {49236: {"300012"}}
        assert struct_names == {"300012": "LIMOS"}

    def test_fallback_to_authIdHasStructure(self):
        doc = {"authIdHasStructure_fs": ["100-200_FacetSep_X_JoinSep_999_FacetSep_Y"]}
        result = parse_author_structures(doc)
        assert result == {100: {"999"}}

    def test_skip_malformed(self):
        doc = {
            "authIdHasPrimaryStructure_fs": [
                "no_join_sep",  # pas de _JoinSep_
                "noformid_FacetSep_Nom_JoinSep_str_FacetSep_Name",  # form_id non int
                "_FacetSep__JoinSep_str_FacetSep_Name",  # form_person vide
                "abc-def_FacetSep_X_JoinSep_999_FacetSep_Y",  # form_id pas un int
                "1-2_FacetSep_X_JoinSep__FacetSep_Y",  # struct_id vide
            ]
        }
        result = parse_author_structures(doc)
        assert result == {}

    def test_multiple_structs_for_same_form(self):
        doc = {
            "authIdHasPrimaryStructure_fs": [
                "100-200_FacetSep_X_JoinSep_111_FacetSep_A",
                "100-200_FacetSep_X_JoinSep_222_FacetSep_B",
            ]
        }
        result = parse_author_structures(doc)
        assert result == {100: {"111", "222"}}


# ── build_hal_author_records (parsing pur) ───────────────────────


class TestBuildHalAuthorRecords:
    def test_no_authors(self):
        assert build_hal_author_records({}) == []

    def test_skip_empty_name(self):
        records = build_hal_author_records(
            {
                "authFullNameFormIDPersonIDIDHal_fs": [
                    "_FacetSep_0-0_FacetSep_",
                    "Marie Dupont_FacetSep_0-0_FacetSep_",
                ]
            }
        )
        assert len(records) == 1
        assert records[0].raw_name == "Marie Dupont"

    def test_composite_extracts_name_and_hal_person_id(self):
        # Le composite fournit le nom et le hal_person_id (2e segment). L'idhal
        # vient du TEI, pas du composite (cf. test suivant).
        doc = {
            "authFullNameFormIDPersonIDIDHal_fs": [
                "Marie Dupont_FacetSep_49236-749496_FacetSep_marie-dupont"
            ],
        }
        record = build_hal_author_records(doc)[0]
        assert record.raw_name == "Marie Dupont"
        # Pas de TEI → pas d'idhal (le 3e segment du composite est ignoré).
        assert record.person_identifiers == {"hal_person_id": 749496}

    def test_idhal_comes_from_tei(self):
        # L'idhal slug vient du TEI (notation="string"), aligné par position.
        label_xml = (
            '<TEI xmlns="http://www.tei-c.org/ns/1.0"><biblFull><titleStmt>'
            '<author><idno type="idhal" notation="string">marie-dupont</idno></author>'
            "</titleStmt></biblFull></TEI>"
        )
        doc = {
            "authFullNameFormIDPersonIDIDHal_fs": [
                "Marie Dupont_FacetSep_49236-749496_FacetSep_marie-dupont"
            ],
            "label_xml": label_xml,
        }
        assert build_hal_author_records(doc)[0].person_identifiers == {
            "idhal": "marie-dupont",
            "hal_person_id": 749496,
        }

    def test_composite_numeric_idhal_not_promoted(self):
        # Régression : quand l'auteur n'a pas de slug, HAL recopie le person_id
        # numérique dans le 3e segment du composite. Sans idhal TEI, on ne doit
        # PAS créer d'idhal numérique (== hal_person_id) — seul hal_person_id reste.
        doc = {
            "authFullNameFormIDPersonIDIDHal_fs": [
                "Christian Duale_FacetSep_106-921527_FacetSep_921527"
            ],
        }
        assert build_hal_author_records(doc)[0].person_identifiers == {
            "hal_person_id": 921527,
        }

    def test_composite_with_zero_person_id_filtered(self):
        """person_id == 0 = non identifié par HAL, on l'ignore."""
        doc = {
            "authFullNameFormIDPersonIDIDHal_fs": ["X_FacetSep_49236-0_FacetSep_"],
        }
        # Sans hal_person_id ni idhal, person_identifiers est None.
        assert build_hal_author_records(doc)[0].person_identifiers is None

    def test_duplicate_hal_person_id_marks_all_identifiers_dubious(self):
        """Un même hal_person_id sur ≥2 auteurs du dépôt (erreur HAL) rend TOUTE
        l'identité douteuse : tous les identifiants de ces signatures (ici
        hal_person_id + idref, attachés au compte HAL) passent sous une clé
        `_dubious`. Les comptes non dupliqués restent intacts."""
        label_xml = (
            '<TEI xmlns="http://www.tei-c.org/ns/1.0"><biblFull><titleStmt>'
            '<author><idno type="IDREF">111111111</idno></author>'
            '<author><idno type="IDREF">111111111</idno></author>'
            "<author></author>"
            "</titleStmt></biblFull></TEI>"
        )
        doc = {
            "authFullNameFormIDPersonIDIDHal_fs": [
                "Marie Dupont_FacetSep_49236-749496_FacetSep_",
                "Jean Martin_FacetSep_10000-749496_FacetSep_",
                "Sophie Bernard_FacetSep_20000-555_FacetSep_",
            ],
            "label_xml": label_xml,
        }
        records = build_hal_author_records(doc)
        assert records[0].person_identifiers == {
            "hal_person_id_dubious": 749496,
            "idref_dubious": "111111111",
        }
        assert records[1].person_identifiers == {
            "hal_person_id_dubious": 749496,
            "idref_dubious": "111111111",
        }
        assert records[2].person_identifiers == {"hal_person_id": 555}

    def test_form_struct_map_resolves_addr_parts(self):
        doc = {
            "authFullNameFormIDPersonIDIDHal_fs": ["X_FacetSep_49236-749496_FacetSep_"],
            "authIdHasPrimaryStructure_fs": [
                "49236-749496_FacetSep_X_JoinSep_300012_FacetSep_LIMOS"
            ],
        }
        record = build_hal_author_records(doc)[0]
        assert [a.text for a in record.addresses] == ["LIMOS"]

    def test_quality_maps_to_roles(self):
        """`authQuality_s = 'dir'` est mappé en rôle via `map_role('hal', ...)` (cf. domain.publications.authorship_roles)."""
        doc = {
            "authFullNameFormIDPersonIDIDHal_fs": ["Director_FacetSep_0-0_FacetSep_"],
            "authQuality_s": ["dir"],
        }
        record = build_hal_author_records(doc)[0]
        # On valide juste que map_role a été appelé et a produit une liste non-vide.
        assert record.roles is not None
        assert len(record.roles) > 0


class TestProcessAuthors:
    def test_clears_then_writes_even_when_empty(self):
        authorship_queries = _FakeAuthorshipQueries()
        normalize_hal.process_authorships(MagicMock(), authorship_queries, {}, 10)
        # Le writer clear toujours, même sans auteur (re-traitement → table blanche).
        assert authorship_queries.cleared_for == [10]


# ── process_work ─────────────────────────────────────────────────


@pytest.fixture
def stub_orchestration_deps(monkeypatch):
    """Stub les helpers internes pour ne tester que la boucle process_work."""
    monkeypatch.setattr(normalize_hal, "extract_pub_metadata", lambda d, j: {"journal_id": j})
    monkeypatch.setattr(normalize_hal, "insert_hal_document", lambda *a, **kw: 555)
    monkeypatch.setattr(normalize_hal, "process_authorships", lambda *a, **kw: None)
    monkeypatch.setattr(normalize_hal, "upsert_publisher", lambda name, **kw: 1)
    monkeypatch.setattr(normalize_hal, "upsert_journal", lambda d, p, **kw: 2)


class TestProcessWork:
    def _kwargs(self, queries=None, staging_queries=None):
        return {
            "queries": queries or _FakeQueries(),
            "logger": logging.getLogger("test"),
            "journal_repo": MagicMock(),
            "publisher_repo": MagicMock(),
            "pub_repo": MagicMock(),
            "staging_queries": staging_queries or _FakeStagingQueries(),
            "authorship_queries": _FakeAuthorshipQueries(),
        }

    def test_happy_path(self, stub_orchestration_deps):
        sq = _FakeStagingQueries()
        raw = {
            "title_s": ["T"],
            "producedDateY_i": 2024,
            "authFullNameFormIDPersonIDIDHal_fs": ["T_FacetSep_0-0_FacetSep_"],
        }
        row = _staging_row(staging_id=1, hal_id="hal-1", raw=raw)
        result = process_work(MagicMock(), staging_row=row, **self._kwargs(staging_queries=sq))
        assert result is True
        assert sq.marked_done == [1]

    def test_missing_minimal_metadata_returns_false(self, stub_orchestration_deps, caplog):
        sq = _FakeStagingQueries()
        row = _staging_row(staging_id=1, raw={"title_s": []})  # pas de titre / pas d'année
        with caplog.at_level(logging.WARNING):
            result = process_work(MagicMock(), staging_row=row, **self._kwargs(staging_queries=sq))
        assert result is False
        assert "manquant" in caplog.text
        # Marqué traité : un doc sans titre ni année n'a aucune chance d'aboutir.
        assert sq.marked_done == [1]

    def test_missing_author_field_marks_done(self, stub_orchestration_deps, caplog):
        sq = _FakeStagingQueries()
        # Métadonnées minimales OK mais champ auteurs absent → doc inexploitable.
        row = _staging_row(
            staging_id=2, hal_id="hal-2", raw={"title_s": ["T"], "producedDateY_i": 2024}
        )
        with caplog.at_level(logging.ERROR):
            result = process_work(MagicMock(), staging_row=row, **self._kwargs(staging_queries=sq))
        assert result is False
        assert "inexploitable" in caplog.text
        assert sq.marked_done == [2]

    def test_no_publisher_name_no_upsert(self, monkeypatch):
        """Si ni journalPublisher_s ni publisher_s n'est présent, upsert_publisher n'est pas appelé."""
        captured = {"called": False}

        def fake_upsert_pub(name, **kw):
            captured.called = True
            return 1

        monkeypatch.setattr(normalize_hal, "upsert_publisher", fake_upsert_pub)
        monkeypatch.setattr(normalize_hal, "upsert_journal", lambda d, p, **kw: 2)
        monkeypatch.setattr(normalize_hal, "extract_pub_metadata", lambda d, j: {"journal_id": j})
        monkeypatch.setattr(normalize_hal, "insert_hal_document", lambda *a, **kw: 555)
        monkeypatch.setattr(normalize_hal, "process_authorships", lambda *a, **kw: None)

        raw = {
            "title_s": ["T"],
            "producedDateY_i": 2024,
            "authFullNameFormIDPersonIDIDHal_fs": ["T_FacetSep_0-0_FacetSep_"],
        }
        row = _staging_row(raw=raw)
        process_work(MagicMock(), staging_row=row, **self._kwargs())
        assert captured["called"] is False

    def test_exception_propagated(self, monkeypatch):
        """process_work laisse remonter l'exception ; le log incombe à la boucle de base."""

        def boom(*args, **kw):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(normalize_hal, "upsert_publisher", boom)
        monkeypatch.setattr(normalize_hal, "upsert_journal", lambda d, p, **kw: 2)

        raw = {
            "title_s": ["T"],
            "producedDateY_i": 2024,
            "journalPublisher_s": "Elsevier",
            "authFullNameFormIDPersonIDIDHal_fs": ["T_FacetSep_0-0_FacetSep_"],
        }
        row = _staging_row(hal_id="hal-x", raw=raw)
        with pytest.raises(RuntimeError, match="kaboom"):
            process_work(MagicMock(), staging_row=row, **self._kwargs())


# ── HalNormalizer (classe) ───────────────────────────────────────


def _make_normalizer():
    return HalNormalizer(
        conn=MagicMock(),
        logger=logging.getLogger("test"),
        staging_queries=_FakeStagingQueries(),
        queries=_FakeQueries(),
        journal_repo_factory=lambda c: MagicMock(),
        publisher_repo_factory=lambda c: MagicMock(),
        pub_repo_factory=lambda c: MagicMock(),
        authorship_queries=_FakeAuthorshipQueries(),
    )


class TestHalNormalizerClass:
    def test_preload_caches_sets_repos(self):
        norm = _make_normalizer()
        norm.preload_caches(MagicMock())
        assert norm._journal_repo is not None
        assert norm._publisher_repo is not None
        assert norm._pub_repo is not None

    def test_process_work_delegates(self, monkeypatch):
        norm = _make_normalizer()
        norm.preload_caches(MagicMock())
        monkeypatch.setattr(normalize_hal, "process_work", lambda *a, **kw: True)
        result = norm.process_work(MagicMock(), _staging_row())
        assert result is True
