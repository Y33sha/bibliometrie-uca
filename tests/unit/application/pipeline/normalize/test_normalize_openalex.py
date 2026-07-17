"""Tests unitaires de `application.pipeline.normalize.normalize_openalex`.

Couvre les helpers de parsing (extract_locations_data, reconstruct_abstract, extract_topics), les branches de `upsert_journal` / `insert_openalex_document`, le parsing auteurs `build_openalex_author_records`, l'orchestrateur `process_work`, et la classe `OpenalexNormalizer` (preload_caches / process_work wrapper / summary_stats).

Pattern : `_FakeQueries` + `MagicMock` pour repos / authorship_queries. Pas de DB.
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
    build_openalex_author_records,
    extract_locations_data,
    extract_pub_metadata,
    extract_topics,
    insert_openalex_document,
    process_work,
    reconstruct_abstract,
    upsert_journal,
)
from application.ports.pipeline.normalize.source_publications import SourcePublicationRow
from application.ports.pipeline.normalize.staging import StagingRow

# ── Helpers de fabrication de données de test ────────────────────


def _staging_row(staging_id=1, source_id="W:1", doi=None, raw=None):
    return StagingRow(id=staging_id, source_id=source_id, doi=doi, raw_data=raw or {})


class _FakeQueries:
    """Stub minimal du port `SourcePublicationQueries`."""

    def __init__(self) -> None:
        self.upserted_documents: list[SourcePublicationRow] = []

    def upsert_source_publication(self, conn, row) -> int:
        self.upserted_documents.append(row)
        return 999


class _FakeStagingQueries:
    def __init__(self) -> None:
        self.marked_done: list[int] = []

    def mark_done(self, conn, staging_id: int) -> None:
        self.marked_done.append(staging_id)


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

    def test_collects_all_location_dois(self):
        """DOI collectés depuis les URLs doi.org ET les location.id `doi:`,
        dédupliqués. Le retrait du primaire est fait par l'appelant."""
        work = {
            "locations": [
                {"landing_page_url": "https://doi.org/10.1/a", "id": "doi:10.1/a"},
                {"landing_page_url": "https://doi.org/10.2/b"},
                {"id": "doi:10.3/c"},
            ]
        }
        _, ids = extract_locations_data(work)
        assert ids["related_dois"] == ["10.1/a", "10.2/b", "10.3/c"]


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


# ── _extract_openalex_orcid ──────────────────────────────────────


class TestExtractOpenalexOrcid:
    def test_empty_authorship(self):
        assert _extract_openalex_orcid({}) is None

    def test_raw_orcid_present(self):
        # On lit `raw_orcid` (déposé par l'auteur), normalisé (préfixe URL strippé).
        result = _extract_openalex_orcid({"raw_orcid": "https://orcid.org/0000-0001-2345-6789"})
        assert result == "0000-0001-2345-6789"

    def test_author_orcid_ignored(self):
        """`author.orcid` (entité désambiguïsée OA) est ignoré au profit de `raw_orcid`."""
        assert _extract_openalex_orcid({"author": {"orcid": "0000-0001-2345-6789"}}) is None

    def test_no_raw_orcid(self):
        assert _extract_openalex_orcid({"raw_orcid": None}) is None


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
        # Par défaut, pub_meta est dérivé via extract_pub_metadata pour rester
        # cohérent avec le flux réel (extract → insert). Tests qui veulent
        # forcer une valeur passent un pub_meta explicite.
        if pub_meta is None:
            pub_meta = extract_pub_metadata(work, journal_id=None)
        insert_openalex_document(MagicMock(), queries, work, staging_id=1, pub_meta=pub_meta)
        return queries.upserted_documents[-1]

    def test_keywords_list_of_strings(self):
        queries = _FakeQueries()
        work = {"id": "https://openalex.org/W1", "keywords": ["a", "b"]}
        captured = self._call(queries, work)
        assert captured.keywords == ["a", "b"]

    def test_keywords_list_of_dicts(self):
        queries = _FakeQueries()
        work = {
            "id": "https://openalex.org/W1",
            "keywords": [{"keyword": "kw1"}, {"keyword": "kw2"}],
        }
        captured = self._call(queries, work)
        assert captured.keywords == ["kw1", "kw2"]

    def test_keywords_not_a_list(self):
        queries = _FakeQueries()
        work = {"id": "https://openalex.org/W1", "keywords": "scalar"}
        captured = self._call(queries, work)
        assert captured.keywords is None

    def test_biblio_extracted(self):
        queries = _FakeQueries()
        work = {
            "id": "https://openalex.org/W1",
            "biblio": {"volume": "10", "issue": "2", "first_page": "100", "last_page": "120"},
        }
        captured = self._call(queries, work)
        assert captured.biblio == {
            "volume": "10",
            "issue": "2",
            "first_page": "100",
            "last_page": "120",
        }

    def test_biblio_partial_drops_empty_keys(self):
        queries = _FakeQueries()
        work = {"id": "https://openalex.org/W1", "biblio": {"volume": "10"}}
        captured = self._call(queries, work)
        assert captured.biblio == {"volume": "10"}

    def test_biblio_empty_is_none(self):
        queries = _FakeQueries()
        captured = self._call(queries, {"id": "https://openalex.org/W1", "biblio": {}})
        assert captured.biblio is None

    def test_related_dois_excludes_primary(self):
        queries = _FakeQueries()
        work = {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1/primary",
            "locations": [
                {"landing_page_url": "https://doi.org/10.1/primary"},
                {"id": "doi:10.2/preprint"},
            ],
        }
        captured = self._call(queries, work)
        assert captured.external_ids["related_dois"] == ["10.2/preprint"]

    def test_related_dois_absent_when_only_primary(self):
        queries = _FakeQueries()
        work = {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1/primary",
            "locations": [{"landing_page_url": "https://doi.org/10.1/primary"}],
        }
        captured = self._call(queries, work)
        assert "related_dois" not in (captured.external_ids or {})

    def test_biblio_publisher_and_journal_from_primary_location(self):
        queries = _FakeQueries()
        work = {
            "id": "https://openalex.org/W1",
            "primary_location": {
                "source": {
                    "host_organization_name": "Elsevier",
                    "display_name": "Journal of Physics",
                    "id": "https://openalex.org/S123",
                    "issn": ["0022-3727", "1361-6463"],
                    "issn_l": "0022-3727",
                }
            },
        }
        captured = self._call(queries, work)
        # `issn_l` est mis dans `issnl` ; le premier non-issn_l de la liste passe en
        # `issn` (pas de typage `electronic`/`print` côté OpenAlex sur ce chemin).
        assert captured.biblio == {
            "publisher": "Elsevier",
            "journal": {
                "title": "Journal of Physics",
                "issn": "1361-6463",
                "issnl": "0022-3727",
                "openalex_id": "S123",
            },
        }

    def test_biblio_skipped_when_primary_is_repository(self, monkeypatch):
        """Si should_skip_publisher_journal renvoie True, publisher/journal absents de biblio."""

        class _PrimaryStub:
            source_display_name = None

        monkeypatch.setattr(normalize_openalex, "parse_primary_location", lambda w: _PrimaryStub())
        monkeypatch.setattr(normalize_openalex, "is_theses_fr_location", lambda p: False)
        monkeypatch.setattr(normalize_openalex, "should_skip_publisher_journal", lambda p: True)
        queries = _FakeQueries()
        work = {
            "id": "https://openalex.org/W1",
            "primary_location": {"source": {"host_organization_name": "HAL"}},
        }
        captured = self._call(queries, work)
        assert captured.biblio is None

    def test_pub_meta_nnt_passed_through_to_external_ids(self):
        """insert lit pub_meta["nnt"] et le pose dans external_ids."""
        queries = _FakeQueries()
        work = {"id": "https://openalex.org/W1"}
        pub_meta = extract_pub_metadata(work, journal_id=None)
        pub_meta["nnt"] = "2024CLFAC001"
        captured = self._call(queries, work, pub_meta=pub_meta)
        assert captured.external_ids is not None
        assert captured.external_ids["nnt"] == "2024CLFAC001"

    def test_pub_meta_source_doi_passed_through(self):
        """Si `pub_meta` contient `source_doi`, il est repris dans external_ids."""
        queries = _FakeQueries()
        work = {"id": "https://openalex.org/W1"}
        pub_meta = extract_pub_metadata(work, journal_id=None)
        pub_meta["source_doi"] = "10.1234/abc"
        captured = self._call(queries, work, pub_meta=pub_meta)
        assert captured.external_ids["source_doi"] == "10.1234/abc"


# ── build_openalex_author_records (parsing pur) ──────────────────


class TestBuildOpenalexAuthorRecords:
    def test_no_authorships(self):
        assert build_openalex_author_records({"authorships": []}) == []

    def test_shared_orcid_marked_dubious(self):
        """ORCID hérité de crossref recopié sur 2 signatures du work → `_dubious`."""
        work = {
            "authorships": [
                {
                    "raw_author_name": "S. Acharya",
                    "raw_orcid": "https://orcid.org/0000-0001-2345-6789",
                },
                {"raw_author_name": "S. Das", "raw_orcid": "https://orcid.org/0000-0001-2345-6789"},
            ]
        }
        recs = build_openalex_author_records(work)
        assert [r.person_identifiers for r in recs] == [
            {"orcid_dubious": "0000-0001-2345-6789"},
            {"orcid_dubious": "0000-0001-2345-6789"},
        ]

    def test_skip_without_raw_name(self):
        # Sans raw_author_name → authorship inexploitable, ignorée.
        records = build_openalex_author_records(
            {"authorships": [{"author": {"display_name": "X"}}]}
        )
        assert records == []

    def test_orcid_corresponding_and_roles(self):
        work = {
            "authorships": [
                {
                    "raw_author_name": "DUPONT Marie",
                    "raw_orcid": "https://orcid.org/0000-0001-2345-6789",
                    # author.orcid divergent : doit être ignoré au profit de raw_orcid.
                    "author": {"orcid": "https://orcid.org/9999-9999-9999-9999"},
                    "is_corresponding": True,
                    "raw_affiliation_strings": ["Univ Clermont"],
                    "institutions": [],
                }
            ]
        }
        rec = build_openalex_author_records(work)[0]
        assert rec.raw_name == "DUPONT Marie"
        assert rec.is_corresponding is True
        # roles posé explicitement (reproduit l'ancien défaut DB ARRAY['author']).
        assert rec.roles == ["author"]
        assert rec.person_identifiers == {"orcid": "0000-0001-2345-6789"}
        assert [a.text for a in rec.addresses] == ["Univ Clermont"]

    def test_institutions_as_addr_fallback(self):
        """Sans raw_affiliation_strings, on tombe sur les institutions display_name."""
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
        rec = build_openalex_author_records(work)[0]
        assert [a.text for a in rec.addresses] == ["Inst One", "Inst Two"]

    def test_no_addr_when_no_affiliation(self):
        work = {"authorships": [{"raw_author_name": "X", "institutions": []}]}
        assert build_openalex_author_records(work)[0].addresses == []

    def test_country_code_to_suggested(self):
        """`country_code` OpenAlex (structure désambiguïsée) → `suggested_countries`
        sur l'adresse, jamais `countries`. Union dédupliquée et en minuscules
        (code canonique = `countries.code`)."""
        work = {
            "authorships": [
                {
                    "raw_author_name": "X",
                    "raw_affiliation_strings": ["Some affiliation"],
                    "institutions": [
                        {
                            "id": "https://openalex.org/I1",
                            "display_name": "A",
                            "country_code": "FR",
                        },
                        {
                            "id": "https://openalex.org/I2",
                            "display_name": "B",
                            "country_code": "us",
                        },
                    ],
                }
            ]
        }
        addr = build_openalex_author_records(work)[0].addresses[0]
        assert addr.suggested_countries == ["fr", "us"]
        assert addr.countries is None

    def test_no_country_code_no_suggestion(self):
        work = {
            "authorships": [
                {
                    "raw_author_name": "X",
                    "raw_affiliation_strings": ["Some affiliation"],
                    "institutions": [{"id": "https://openalex.org/I1", "display_name": "A"}],
                }
            ]
        }
        assert build_openalex_author_records(work)[0].addresses[0].suggested_countries is None


# ── process_work (orchestrateur) ─────────────────────────────────


@pytest.fixture
def stub_orchestration_deps(monkeypatch):
    """Stub les helpers internes pour ne tester que la boucle process_work."""
    monkeypatch.setattr(
        normalize_openalex, "extract_pub_metadata", lambda w, j, primary=None: {"journal_id": j}
    )
    monkeypatch.setattr(
        normalize_openalex,
        "insert_openalex_document",
        lambda *a, **kw: 555,
    )
    monkeypatch.setattr(normalize_openalex, "process_authorships", lambda *a, **kw: None)
    monkeypatch.setattr(normalize_openalex, "parse_primary_location", lambda w: None)
    monkeypatch.setattr(normalize_openalex, "should_skip_publisher_journal", lambda p: True)


class TestProcessWork:
    def _kwargs(self, queries=None, staging_queries=None, logger_=None):
        return {
            "queries": queries or _FakeQueries(),
            "logger": logger_ or logging.getLogger("test"),
            "journal_repo": MagicMock(),
            "publisher_repo": MagicMock(),
            "publication_repo": MagicMock(),
            "staging_queries": staging_queries or _FakeStagingQueries(),
            "authorship_queries": MagicMock(),
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

    def test_should_skip_publisher_journal_false_calls_upserts(self, monkeypatch):
        """Quand should_skip_publisher_journal renvoie False, upsert_publisher / upsert_journal sont appelés."""
        monkeypatch.setattr(normalize_openalex, "parse_primary_location", lambda w: object())
        monkeypatch.setattr(normalize_openalex, "should_skip_publisher_journal", lambda p: False)
        monkeypatch.setattr(normalize_openalex, "upsert_publisher", lambda w, **kw: 1)
        monkeypatch.setattr(normalize_openalex, "upsert_journal", lambda w, p, **kw: 2)
        monkeypatch.setattr(
            normalize_openalex, "extract_pub_metadata", lambda w, j, primary=None: {"journal_id": j}
        )
        monkeypatch.setattr(normalize_openalex, "insert_openalex_document", lambda *a, **kw: 555)
        monkeypatch.setattr(normalize_openalex, "process_authorships", lambda *a, **kw: None)

        row = _staging_row()
        result = process_work(MagicMock(), staging_row=row, **self._kwargs())
        assert result is True

    def test_exception_propagated(self, monkeypatch):
        """process_work laisse remonter l'exception ; le log incombe à la boucle de base."""
        monkeypatch.setattr(
            normalize_openalex,
            "parse_primary_location",
            lambda w: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        row = _staging_row(staging_id=1, source_id="W1")
        with pytest.raises(RuntimeError, match="boom"):
            process_work(MagicMock(), staging_row=row, **self._kwargs())


# ── OpenalexNormalizer (classe) ──────────────────────────────────


def _make_normalizer():
    return OpenalexNormalizer(
        conn=MagicMock(),
        logger=logging.getLogger("test"),
        staging_queries=_FakeStagingQueries(),
        queries=_FakeQueries(),
        journal_repo_factory=lambda c: MagicMock(),
        publisher_repo_factory=lambda c: MagicMock(),
        publication_repo_factory=lambda c: MagicMock(),
        authorship_queries=MagicMock(),
    )


class TestOpenalexNormalizerClass:
    def test_preload_caches_sets_repos(self):
        norm = _make_normalizer()
        norm.preload_caches(MagicMock())
        assert norm._journal_repo is not None
        assert norm._publisher_repo is not None
        assert norm._publication_repo is not None

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
            "publication_repo",
            "staging_queries",
            "authorship_queries",
        }
