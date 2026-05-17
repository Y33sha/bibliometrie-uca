"""Tests unitaires de `application.pipeline.normalize.normalize_openalex`.

Couvre les helpers de parsing (extract_locations_data, reconstruct_abstract, extract_topics, extract_short_id), les branches de `upsert_journal` / `insert_openalex_document`, l'orchestrateur `process_authorships`, l'orchestrateur `process_work` (avec ses cas Zenodo), et la classe `OpenalexNormalizer` (preload_caches / _row_factory / process_work wrapper / cleanup / on_error / summary_stats).

Pattern : `_FakeQueries` + `_FakeAddressLinker` + `MagicMock` pour repos / zenodo_resolver. Pas de DB.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from application.pipeline.normalize import normalize_openalex
from application.pipeline.normalize.normalize_openalex import (
    OpenalexNormalizer,
    _extract_openalex_orcid,
    extract_locations_data,
    extract_pub_metadata,
    extract_short_id,
    extract_topics,
    insert_openalex_document,
    process_authorships,
    process_work,
    reconstruct_abstract,
    upsert_journal,
)
from application.ports.pipeline.staging import StagingRow
from domain.sources.zenodo import ZenodoResolutionError

# ── Helpers de fabrication de données de test ────────────────────


def _staging_row(staging_id=1, source_id="W:1", doi=None, raw=None):
    return StagingRow(id=staging_id, source_id=source_id, doi=doi, raw_data=raw or {})


class _FakeQueries:
    """Stub minimal du port `OpenalexNormalizeQueries`."""

    def __init__(self) -> None:
        self.cleared_for: list[int] = []
        self.upserted_authorships: list[dict[str, Any]] = []
        self.upserted_documents: list[dict[str, Any]] = []
        self.staging_has_doi_returns = False
        self.count_table_returns = 0

    def upsert_openalex_source_publication(self, conn, **kw) -> int:
        self.upserted_documents.append(kw)
        return 999

    def upsert_openalex_source_authorship(self, conn, **kw) -> int:
        self.upserted_authorships.append(kw)
        return 100 + len(self.upserted_authorships)

    def staging_has_openalex_doi(self, conn, doi: str) -> bool:
        return self.staging_has_doi_returns

    def count_openalex_table(self, conn, table: str) -> int:
        return self.count_table_returns

    def clear_source_authorships_for_publication(self, conn, source_publication_id: int) -> None:
        self.cleared_for.append(source_publication_id)


class _FakeAddressLinker:
    def __init__(self) -> None:
        self.links: list[tuple[int, list[str]]] = []
        self.cleared = 0

    def link(self, conn, sa_id: int, addr_parts: list[str]) -> None:
        self.links.append((sa_id, addr_parts))

    def clear_cache(self) -> None:
        self.cleared += 1


class _FakeStagingQueries:
    def __init__(self) -> None:
        self.marked_done: list[int] = []

    def mark_done(self, conn, staging_id: int) -> None:
        self.marked_done.append(staging_id)


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_normalize_openalex")


# ── extract_locations_data ───────────────────────────────────────


class TestExtractLocationsData:
    def test_empty_locations(self):
        urls, ids = extract_locations_data({})
        assert urls == []
        assert ids == {}

    def test_dedup_urls(self):
        work = {
            "locations": [
                {"landing_page_url": "https://a.com/x", "pdf_url": "https://a.com/x.pdf"},
                {"landing_page_url": "https://a.com/x", "pdf_url": "https://a.com/x.pdf"},
            ]
        }
        urls, _ = extract_locations_data(work)
        assert urls == ["https://a.com/x", "https://a.com/x.pdf"]

    def test_skips_falsy_urls(self):
        work = {"locations": [{"landing_page_url": None, "pdf_url": "https://b.com"}]}
        urls, _ = extract_locations_data(work)
        assert urls == ["https://b.com"]


# ── reconstruct_abstract ─────────────────────────────────────────


class TestReconstructAbstract:
    def test_none_input(self):
        assert reconstruct_abstract(None) is None

    def test_empty_dict(self):
        assert reconstruct_abstract({}) is None

    def test_simple_reconstruction(self):
        # "Hello world" : positions 0 et 1
        inverted = {"Hello": [0], "world": [1]}
        assert reconstruct_abstract(inverted) == "Hello world"

    def test_multiple_occurrences(self):
        # "the cat the dog" : 'the' aux positions 0 et 2
        inverted = {"the": [0, 2], "cat": [1], "dog": [3]}
        assert reconstruct_abstract(inverted) == "the cat the dog"

    def test_inverted_index_with_no_positions(self):
        """Inverted index présent mais positions vides → None."""
        assert reconstruct_abstract({"word": []}) is None


# ── extract_topics ───────────────────────────────────────────────


class TestExtractTopics:
    def test_none_topics(self):
        assert extract_topics({}) is None

    def test_empty_topics(self):
        assert extract_topics({"topics": []}) is None

    def test_basic_topic(self):
        work = {
            "topics": [
                {
                    "display_name": "Theory of Computation",
                    "domain": {"display_name": "Computer Science"},
                    "field": {"display_name": "Algorithms"},
                    "subfield": {"display_name": "Complexity"},
                    "score": 0.8,
                }
            ]
        }
        topics = extract_topics(work)
        assert topics is not None
        assert topics[0]["domain"] == "Computer Science"
        assert topics[0]["field"] == "Algorithms"
        assert topics[0]["subfield"] == "Complexity"
        assert topics[0]["topic"] == "Theory of Computation"
        assert topics[0]["score"] == 0.8

    def test_topic_no_score(self):
        work = {"topics": [{"display_name": "Math"}]}
        topics = extract_topics(work)
        assert topics is not None
        assert "score" not in topics[0]

    def test_topic_with_no_displayable_fields(self):
        """Si un topic n'a aucun champ exploitable, il n'est pas inclus."""
        work = {"topics": [{"foo": "bar"}]}  # ni domain, ni field, ni subfield, ni display_name
        assert extract_topics(work) is None


# ── extract_short_id ─────────────────────────────────────────────


class TestExtractShortId:
    def test_with_prefix(self):
        assert extract_short_id("https://openalex.org/W123") == "W123"

    def test_without_prefix(self):
        assert extract_short_id("W123") == "W123"

    def test_empty(self):
        assert extract_short_id("") == ""

    def test_custom_prefix(self):
        assert extract_short_id("ror:abc123", prefix="ror:") == "abc123"


# ── _extract_openalex_orcid ──────────────────────────────────────


class TestExtractOpenalexOrcid:
    def test_no_author(self):
        assert _extract_openalex_orcid({}) is None

    def test_orcid_present(self):
        # ORCID est normalisé (suppression du préfixe URL).
        result = _extract_openalex_orcid(
            {"author": {"orcid": "https://orcid.org/0000-0001-2345-6789"}}
        )
        assert result == "0000-0001-2345-6789"

    def test_no_orcid(self):
        assert _extract_openalex_orcid({"author": {}}) is None


# ── upsert_publisher ─────────────────────────────────────────────


class TestUpsertPublisher:
    def test_no_publisher_name(self):
        from application.pipeline.normalize.normalize_openalex import upsert_publisher

        assert upsert_publisher({}, publisher_repo=MagicMock()) is None

    def test_happy_path(self, monkeypatch):
        from application.pipeline.normalize.normalize_openalex import upsert_publisher

        captured: dict[str, Any] = {}

        def fake_find(name, *, openalex_id, repo):
            captured["name"] = name
            captured["openalex_id"] = openalex_id
            return 7

        monkeypatch.setattr(normalize_openalex, "find_or_create_publisher", fake_find)
        work = {
            "primary_location": {
                "source": {
                    "host_organization_name": "Elsevier",
                    "host_organization": "https://openalex.org/P1",
                }
            }
        }
        result = upsert_publisher(work, publisher_repo=MagicMock())
        assert result == 7
        assert captured["name"] == "Elsevier"
        assert captured["openalex_id"] == "P1"

    def test_no_host_organization_id(self, monkeypatch):
        """Si `host_organization` est absent, `openalex_id` passé est None."""
        from application.pipeline.normalize.normalize_openalex import upsert_publisher

        captured: dict[str, Any] = {}

        def fake_find(name, *, openalex_id, repo):
            captured["openalex_id"] = openalex_id
            return 7

        monkeypatch.setattr(normalize_openalex, "find_or_create_publisher", fake_find)
        work = {"primary_location": {"source": {"host_organization_name": "X"}}}
        upsert_publisher(work, publisher_repo=MagicMock())
        assert captured["openalex_id"] is None


# ── upsert_journal (branches issn/eissn/oa_model) ────────────────


class TestUpsertJournal:
    def test_no_title_returns_none(self):
        repo = MagicMock()
        result = upsert_journal({}, None, journal_repo=repo)
        assert result is None
        repo.create_journal.assert_not_called()

    def test_repository_source_oa_model(self, monkeypatch):
        captured: dict[str, Any] = {}

        def fake_create(*args, **kwargs):
            captured.update(kwargs)
            return 42

        monkeypatch.setattr(normalize_openalex, "find_or_create_journal", fake_create)
        work = {
            "primary_location": {
                "source": {
                    "display_name": "Repo",
                    "id": "https://openalex.org/S1",
                    "type": "repository",
                }
            }
        }
        result = upsert_journal(work, None, journal_repo=MagicMock())
        assert result == 42
        assert captured["oa_model"] == "repository"

    def test_journal_full_oa(self, monkeypatch):
        captured: dict[str, Any] = {}

        def fake_create(*args, **kwargs):
            captured.update(kwargs)
            return 1

        monkeypatch.setattr(normalize_openalex, "find_or_create_journal", fake_create)
        work = {
            "primary_location": {"source": {"display_name": "OA", "type": "journal", "is_oa": True}}
        }
        upsert_journal(work, None, journal_repo=MagicMock())
        assert captured["oa_model"] == "full_oa"

    def test_journal_subscription(self, monkeypatch):
        captured: dict[str, Any] = {}

        def fake_create(*args, **kwargs):
            captured.update(kwargs)
            return 1

        monkeypatch.setattr(normalize_openalex, "find_or_create_journal", fake_create)
        work = {
            "primary_location": {
                "source": {"display_name": "Sub", "type": "journal"}
            }  # is_oa absent
        }
        upsert_journal(work, None, journal_repo=MagicMock())
        assert captured["oa_model"] == "subscription"

    def test_issn_eissn_picked_from_array(self, monkeypatch):
        """Le premier ISSN différent de issn_l alimente issn ; le second alimente eissn."""
        captured: dict[str, Any] = {}

        def fake_create(*args, **kwargs):
            captured.update(kwargs)
            return 1

        monkeypatch.setattr(normalize_openalex, "find_or_create_journal", fake_create)
        work = {
            "primary_location": {
                "source": {
                    "display_name": "J",
                    "issn_l": "1111-1111",
                    "issn": ["1111-1111", "2222-2222", "3333-3333"],
                }
            }
        }
        upsert_journal(work, None, journal_repo=MagicMock())
        assert captured["issn"] == "2222-2222"
        assert captured["eissn"] == "3333-3333"


# ── extract_pub_metadata ─────────────────────────────────────────


class TestExtractPubMetadata:
    def test_minimal_work(self):
        meta = extract_pub_metadata({"title": "T", "publication_year": 2024}, journal_id=None)
        assert meta["title"] == "T"
        assert meta["pub_year"] == 2024
        assert meta["doi"] is None
        assert meta["nnt"] is None
        assert meta["journal_id"] is None

    def test_display_name_fallback(self):
        meta = extract_pub_metadata({"display_name": "DN"}, journal_id=None)
        assert meta["title"] == "DN"

    def test_with_journal_id_no_container_title(self):
        """Si journal_id présent, container_title reste None (la revue identifie tout)."""
        work = {
            "title": "T",
            "primary_location": {"source": {"display_name": "Some Source"}},
        }
        meta = extract_pub_metadata(work, journal_id=42)
        assert meta["container_title"] is None


# ── insert_openalex_document (edge cases) ────────────────────────


class TestInsertOpenalexDocument:
    def _call(self, queries: _FakeQueries, work: dict, *, pub_meta: dict | None = None) -> dict:
        insert_openalex_document(
            MagicMock(), queries, work, staging_id=1, publication_id=None, pub_meta=pub_meta
        )
        return queries.upserted_documents[-1]

    def test_keywords_list_of_strings(self):
        queries = _FakeQueries()
        work = {"id": "https://openalex.org/W1", "keywords": ["a", "b"]}
        captured = self._call(queries, work)
        assert captured["keywords"] == ["a", "b"]

    def test_keywords_list_of_dicts(self):
        queries = _FakeQueries()
        work = {
            "id": "https://openalex.org/W1",
            "keywords": [{"keyword": "kw1"}, {"keyword": "kw2"}],
        }
        captured = self._call(queries, work)
        assert captured["keywords"] == ["kw1", "kw2"]

    def test_keywords_not_a_list(self):
        queries = _FakeQueries()
        work = {"id": "https://openalex.org/W1", "keywords": "scalar"}
        captured = self._call(queries, work)
        assert captured["keywords"] is None

    def test_biblio_extracted(self):
        queries = _FakeQueries()
        work = {
            "id": "https://openalex.org/W1",
            "biblio": {"volume": "10", "issue": "2", "first_page": "100", "last_page": "120"},
        }
        captured = self._call(queries, work)
        assert captured["biblio"] == {
            "volume": "10",
            "issue": "2",
            "first_page": "100",
            "last_page": "120",
        }

    def test_biblio_partial_drops_empty_keys(self):
        queries = _FakeQueries()
        work = {"id": "https://openalex.org/W1", "biblio": {"volume": "10"}}
        captured = self._call(queries, work)
        assert captured["biblio"] == {"volume": "10"}

    def test_biblio_empty_is_none(self):
        queries = _FakeQueries()
        captured = self._call(queries, {"id": "https://openalex.org/W1", "biblio": {}})
        assert captured["biblio"] is None

    def test_theses_fr_nnt_extracted(self, monkeypatch):
        """Si le primary_location est theses.fr, le nnt va dans external_ids."""

        class _PrimaryStub:
            landing_page_url = "https://theses.fr/2024CLFAC001"

        monkeypatch.setattr(normalize_openalex, "parse_primary_location", lambda w: _PrimaryStub())
        monkeypatch.setattr(normalize_openalex, "is_theses_fr_location", lambda p: True)
        monkeypatch.setattr(
            normalize_openalex, "extract_nnt_from_location", lambda p: "2024CLFAC001"
        )

        queries = _FakeQueries()
        captured = self._call(queries, {"id": "https://openalex.org/W1"})
        assert captured["external_ids"] is not None
        assert captured["external_ids"]["nnt"] == "2024CLFAC001"

    def test_pub_meta_source_doi_passed_through(self):
        """Si `pub_meta` contient `source_doi`, il est repris dans external_ids."""
        queries = _FakeQueries()
        captured = self._call(
            queries,
            {"id": "https://openalex.org/W1"},
            pub_meta={"source_doi": "10.1234/abc"},
        )
        assert captured["external_ids"]["source_doi"] == "10.1234/abc"


# ── process_authorships ──────────────────────────────────────────


class TestProcessAuthorships:
    def test_no_authorships(self):
        queries = _FakeQueries()
        process_authorships(
            MagicMock(),
            queries,
            work={"authorships": []},
            source_publication_id=10,
            address_linker=_FakeAddressLinker(),
        )
        assert queries.cleared_for == [10]
        assert queries.upserted_authorships == []

    def test_authorship_without_raw_name_skipped(self):
        queries = _FakeQueries()
        process_authorships(
            MagicMock(),
            queries,
            work={"authorships": [{"author": {"display_name": "X"}}]},  # pas de raw_author_name
            source_publication_id=10,
            address_linker=_FakeAddressLinker(),
        )
        assert queries.upserted_authorships == []

    def test_authorship_with_orcid(self):
        queries = _FakeQueries()
        work = {
            "authorships": [
                {
                    "raw_author_name": "DUPONT Marie",
                    "author": {
                        "orcid": "https://orcid.org/0000-0001-2345-6789",
                        "display_name": "Marie Dupont",
                    },
                    "is_corresponding": True,
                    "raw_affiliation_strings": ["Univ Clermont"],
                    "institutions": [],
                }
            ]
        }
        linker = _FakeAddressLinker()
        process_authorships(
            MagicMock(),
            queries,
            work=work,
            source_publication_id=10,
            address_linker=linker,
        )
        upserted = queries.upserted_authorships[0]
        assert upserted["raw_author_name"] == "DUPONT Marie"
        assert upserted["is_corresponding"] is True
        assert upserted["person_identifiers"] == {"orcid": "0000-0001-2345-6789"}
        assert upserted["source_data"] == {"display_name": "Marie Dupont"}
        # Linker appelé avec l'addresse brute.
        assert linker.links == [(101, ["Univ Clermont"])]

    def test_authorship_institutions_as_addr_fallback(self):
        """Sans raw_affiliation_strings, on tombe sur les institutions display_name."""
        queries = _FakeQueries()
        work = {
            "authorships": [
                {
                    "raw_author_name": "X",
                    "institutions": [
                        {"id": "https://openalex.org/I1", "display_name": "Inst One"},
                        {"id": "https://openalex.org/I2", "display_name": "Inst Two"},
                    ],
                }
            ]
        }
        linker = _FakeAddressLinker()
        process_authorships(
            MagicMock(), queries, work, source_publication_id=10, address_linker=linker
        )
        upserted = queries.upserted_authorships[0]
        # source_structures est rempli depuis les openalex_id natifs des institutions.
        assert upserted["source_structures"] == ["I1", "I2"]
        # addr_parts = display_names des institutions (raw_strings vide).
        assert linker.links == [(101, ["Inst One", "Inst Two"])]

    def test_authorship_no_addr_no_linker_call(self):
        queries = _FakeQueries()
        work = {"authorships": [{"raw_author_name": "X", "institutions": []}]}
        linker = _FakeAddressLinker()
        process_authorships(
            MagicMock(), queries, work, source_publication_id=10, address_linker=linker
        )
        assert linker.links == []

    def test_author_no_display_name_no_source_data(self):
        """Sans `author.display_name`, `source_data` reste None."""
        queries = _FakeQueries()
        work = {"authorships": [{"raw_author_name": "X", "institutions": [], "author": {}}]}
        process_authorships(
            MagicMock(),
            queries,
            work,
            source_publication_id=10,
            address_linker=_FakeAddressLinker(),
        )
        assert queries.upserted_authorships[0]["source_data"] is None


# ── process_work (orchestrateur) ─────────────────────────────────


@pytest.fixture
def stub_orchestration_deps(monkeypatch):
    """Stub les helpers internes pour ne tester que la boucle process_work."""
    monkeypatch.setattr(normalize_openalex, "extract_pub_metadata", lambda w, j: {"journal_id": j})
    monkeypatch.setattr(
        normalize_openalex,
        "insert_openalex_document",
        lambda *a, **kw: 555,
    )
    monkeypatch.setattr(normalize_openalex, "process_authorships", lambda *a, **kw: None)
    monkeypatch.setattr(normalize_openalex, "parse_primary_location", lambda w: None)
    monkeypatch.setattr(normalize_openalex, "should_skip_publisher_journal", lambda p: True)


class TestProcessWork:
    def _kwargs(self, queries=None, staging_queries=None, logger_=None, zenodo=None):
        return {
            "queries": queries or _FakeQueries(),
            "logger": logger_ or logging.getLogger("test"),
            "journal_repo": MagicMock(),
            "publisher_repo": MagicMock(),
            "pub_repo": MagicMock(),
            "zenodo_resolver": zenodo or MagicMock(),
            "staging_queries": staging_queries or _FakeStagingQueries(),
            "address_linker": _FakeAddressLinker(),
        }

    def test_happy_path(self, stub_orchestration_deps):
        queries = _FakeQueries()
        sq = _FakeStagingQueries()
        row = _staging_row(
            staging_id=1, source_id="W1", doi="10.1/a", raw={"id": "https://openalex.org/W1"}
        )
        kw = self._kwargs(queries=queries, staging_queries=sq)
        result = process_work(MagicMock(), staging_row=row, **kw)
        assert result is True
        assert sq.marked_done == [1]

    def test_zenodo_resolution_error_returns_none(self, stub_orchestration_deps, monkeypatch):
        monkeypatch.setattr(normalize_openalex, "is_zenodo_doi", lambda d: True)
        zenodo = MagicMock()
        zenodo.resolve.side_effect = ZenodoResolutionError("zenodo boom")
        sq = _FakeStagingQueries()
        row = _staging_row(doi="10.5281/zenodo.1")
        result = process_work(
            MagicMock(), staging_row=row, **self._kwargs(staging_queries=sq, zenodo=zenodo)
        )
        assert result is None
        # Pas de mark_done : on retentera plus tard.
        assert sq.marked_done == []

    def test_zenodo_concept_already_in_staging_skipped(self, stub_orchestration_deps, monkeypatch):
        monkeypatch.setattr(normalize_openalex, "is_zenodo_doi", lambda d: True)
        zenodo = MagicMock()
        zenodo.resolve.return_value = "10.5281/zenodo.2"
        queries = _FakeQueries()
        queries.staging_has_doi_returns = True  # version DOI déjà en staging
        sq = _FakeStagingQueries()
        row = _staging_row(staging_id=42, doi="10.5281/zenodo.1")
        result = process_work(
            MagicMock(),
            staging_row=row,
            **self._kwargs(queries=queries, staging_queries=sq, zenodo=zenodo),
        )
        assert result is None
        assert sq.marked_done == [42]  # marqué fait pour ne pas re-tenter

    def test_zenodo_version_resolved_but_not_in_staging_continues(
        self, stub_orchestration_deps, monkeypatch
    ):
        """Le DOI Zenodo est résolu mais la version n'est pas en staging — on continue le traitement nominal."""
        monkeypatch.setattr(normalize_openalex, "is_zenodo_doi", lambda d: True)
        zenodo = MagicMock()
        zenodo.resolve.return_value = "10.5281/zenodo.2"
        queries = _FakeQueries()
        queries.staging_has_doi_returns = False
        sq = _FakeStagingQueries()
        row = _staging_row(staging_id=1, doi="10.5281/zenodo.1")
        result = process_work(
            MagicMock(),
            staging_row=row,
            **self._kwargs(queries=queries, staging_queries=sq, zenodo=zenodo),
        )
        assert result is True
        assert sq.marked_done == [1]

    def test_should_skip_publisher_journal_false_calls_upserts(self, monkeypatch):
        """Quand should_skip_publisher_journal renvoie False, upsert_publisher / upsert_journal sont appelés."""
        monkeypatch.setattr(normalize_openalex, "parse_primary_location", lambda w: object())
        monkeypatch.setattr(normalize_openalex, "should_skip_publisher_journal", lambda p: False)
        monkeypatch.setattr(normalize_openalex, "upsert_publisher", lambda w, **kw: 1)
        monkeypatch.setattr(normalize_openalex, "upsert_journal", lambda w, p, **kw: 2)
        monkeypatch.setattr(
            normalize_openalex, "extract_pub_metadata", lambda w, j: {"journal_id": j}
        )
        monkeypatch.setattr(normalize_openalex, "insert_openalex_document", lambda *a, **kw: 555)
        monkeypatch.setattr(normalize_openalex, "process_authorships", lambda *a, **kw: None)

        row = _staging_row()
        result = process_work(MagicMock(), staging_row=row, **self._kwargs())
        assert result is True

    def test_exception_propagated_and_logged(self, monkeypatch, caplog):
        """Toute exception dans le pipeline est loggée et relevée."""
        monkeypatch.setattr(
            normalize_openalex,
            "parse_primary_location",
            lambda w: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        row = _staging_row(staging_id=1, source_id="W1")
        with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
            process_work(MagicMock(), staging_row=row, **self._kwargs())
        assert "W1" in caplog.text and "boom" in caplog.text


# ── OpenalexNormalizer (classe) ──────────────────────────────────


def _make_normalizer():
    return OpenalexNormalizer(
        conn=MagicMock(),
        logger=logging.getLogger("test"),
        staging_queries=_FakeStagingQueries(),
        queries=_FakeQueries(),
        journal_repo_factory=lambda c: MagicMock(),
        publisher_repo_factory=lambda c: MagicMock(),
        pub_repo_factory=lambda c: MagicMock(),
        zenodo_resolver=MagicMock(),
        address_linker=_FakeAddressLinker(),
    )


class TestOpenalexNormalizerClass:
    def test_preload_caches_sets_repos(self):
        norm = _make_normalizer()
        norm.preload_caches(MagicMock())
        assert norm._journal_repo is not None
        assert norm._publisher_repo is not None
        assert norm._pub_repo is not None

    def test_row_factory_maps_to_staging_row(self):
        norm = _make_normalizer()
        raw = MagicMock()
        raw.id = 7
        raw.source_id = "W7"
        raw.doi = "10.1/x"
        raw.raw_data = {"id": "W7"}
        out = norm._row_factory(raw)
        assert out == StagingRow(id=7, source_id="W7", doi="10.1/x", raw_data={"id": "W7"})

    def test_process_work_delegates_to_module_function(self, monkeypatch):
        norm = _make_normalizer()
        norm.preload_caches(MagicMock())
        captured = {}

        def fake_process(*args, **kwargs):
            captured.update(kwargs)
            return True

        monkeypatch.setattr(normalize_openalex, "process_work", fake_process)
        result = norm.process_work(MagicMock(), _staging_row())
        assert result is True
        # Les dépendances injectées sont passées en kwargs.
        assert set(captured.keys()) >= {
            "journal_repo",
            "publisher_repo",
            "pub_repo",
            "zenodo_resolver",
            "staging_queries",
            "address_linker",
        }

    def test_cleanup_clears_address_linker_cache(self):
        norm = _make_normalizer()
        norm.cleanup()
        assert norm._address_linker.cleared == 1  # type: ignore[attr-defined]

    def test_on_error_clears_address_linker_cache(self):
        norm = _make_normalizer()
        norm.on_error()
        assert norm._address_linker.cleared == 1  # type: ignore[attr-defined]

    def test_summary_stats_calls_count_table(self):
        norm = _make_normalizer()
        norm._queries.count_table_returns = 42  # type: ignore[attr-defined]
        lines = norm.summary_stats(MagicMock())
        assert len(lines) == 1
        assert "42" in lines[0]
