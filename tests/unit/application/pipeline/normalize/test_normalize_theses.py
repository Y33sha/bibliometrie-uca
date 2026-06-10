"""Tests unitaires de `application.pipeline.normalize.normalize_theses`.

Couvre `extract_pub_metadata` (cascade pub_year soutenance/inscription, NNT, doc_type), `_build_source_meta` (date_soutenance, date_inscription, discipline, écoles doctorales, partenaires), `insert_source_document` (keywords sujets, topics discipline+rameau, NNT external_ids), `process_persons` (aggregate_thesis_persons, partenaires → addr_parts), `process_work` (skip sans titre, happy path, exception), et la classe `ThesesNormalizer` (preload, _row_factory, process_work wrapper, cleanup, on_error, summary_stats).

Pattern : `_FakeQueries` + `_FakeAddressLinker` + `MagicMock`, pas de DB.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from application.pipeline.normalize import normalize_theses
from application.pipeline.normalize.normalize_theses import (
    ThesesNormalizer,
    _build_source_meta,
    extract_pub_metadata,
    insert_source_document,
    process_persons,
    process_work,
)
from application.ports.pipeline.staging import StagingRow

# ── Stubs ────────────────────────────────────────────────────────


def _staging_row(staging_id=1, theses_id="2024CLFAC001", raw=None):
    return StagingRow(id=staging_id, source_id=theses_id, doi=None, raw_data=raw or {})


class _FakeQueries:
    def __init__(self) -> None:
        self.cleared_for: list[int] = []
        self.upserted_authorships: list[dict[str, Any]] = []
        self.upserted_documents: list[dict[str, Any]] = []
        self.count_table_returns: dict[str, int] = {}

    def upsert_theses_source_publication(self, conn, **kw) -> int:
        self.upserted_documents.append(kw)
        return 999

    def upsert_theses_source_authorship(self, conn, **kw) -> int:
        self.upserted_authorships.append(kw)
        return 100 + len(self.upserted_authorships)

    def clear_source_authorships_for_publication(self, conn, source_publication_id: int) -> None:
        self.cleared_for.append(source_publication_id)

    def count_theses_table(self, conn, table: str) -> int:
        return self.count_table_returns.get(table, 0)


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


# ── extract_pub_metadata ─────────────────────────────────────────


class TestExtractPubMetadata:
    def test_minimal(self):
        meta = extract_pub_metadata({"titrePrincipal": "T"})
        assert meta["title"] == "T"
        assert meta["pub_year"] is None
        assert meta["nnt"] is None
        assert meta["oa_status"] == "closed"
        assert meta["journal_id"] is None

    def test_pub_year_from_soutenance(self):
        meta = extract_pub_metadata({"titrePrincipal": "T", "dateSoutenance": "15/03/2024"})
        assert meta["pub_year"] == 2024

    def test_pub_year_fallback_to_inscription(self):
        """Si pas de date_soutenance, on prend date_inscription."""
        meta = extract_pub_metadata(
            {"titrePrincipal": "T", "datePremiereInscriptionDoctorat": "10/09/2020"}
        )
        assert meta["pub_year"] == 2020

    def test_pub_year_soutenance_wins_over_inscription(self):
        meta = extract_pub_metadata(
            {
                "titrePrincipal": "T",
                "dateSoutenance": "15/03/2024",
                "datePremiereInscriptionDoctorat": "10/09/2020",
            }
        )
        assert meta["pub_year"] == 2024

    def test_no_title_no_normalized(self):
        meta = extract_pub_metadata({})
        assert meta["title"] is None
        assert meta["title_normalized"] is None

    def test_nnt_normalized(self):
        meta = extract_pub_metadata({"titrePrincipal": "T", "nnt": "  2024clfac001  "})
        assert meta["nnt"] == "2024CLFAC001"

    def test_doi_passthrough(self):
        meta = extract_pub_metadata({"titrePrincipal": "T", "doi": "10.1/abc"})
        assert meta["doi"] == "10.1/abc"


# ── _build_source_meta ───────────────────────────────────────────


class TestBuildSourceMeta:
    def test_empty(self):
        assert _build_source_meta({}) is None

    def test_only_soutenance(self):
        meta = _build_source_meta({"dateSoutenance": "15/03/2024"})
        assert meta == {"date_soutenance": "2024-03-15"}

    def test_etablissement(self):
        meta = _build_source_meta({"etabSoutenanceN": "Université Clermont Auvergne (2021-...)"})
        assert meta == {"etablissement": "Université Clermont Auvergne (2021-...)"}

    def test_full(self):
        these = {
            "dateSoutenance": "15/03/2024",
            "datePremiereInscriptionDoctorat": "10/09/2020",
            "discipline": "Informatique",
            "etabSoutenanceN": "Université Clermont Auvergne (2021-...)",
            "ecolesDoctorale": [{"nom": "EDSPI", "ppn": "1234"}, {"nom": "EDMS"}],
            "partenairesDeRecherche": [
                {"nom": "LIMOS", "type": "labo"},
                {"nom": "LRL"},
            ],
        }
        meta = _build_source_meta(these)
        assert meta is not None
        assert meta["date_soutenance"] == "2024-03-15"
        assert meta["date_inscription"] == "2020-09-10"
        assert meta["discipline"] == "Informatique"
        assert meta["etablissement"] == "Université Clermont Auvergne (2021-...)"
        assert meta["ecoles_doctorales"] == [
            {"nom": "EDSPI", "ppn": "1234"},
            {"nom": "EDMS", "ppn": None},
        ]
        assert meta["partenaires"] == [
            {"nom": "LIMOS", "type": "labo"},
            {"nom": "LRL", "type": None},
        ]

    def test_filters_ecoles_without_nom(self):
        meta = _build_source_meta({"ecolesDoctorale": [{"ppn": "123"}, {"nom": "EDSPI"}]})
        assert meta == {"ecoles_doctorales": [{"nom": "EDSPI", "ppn": None}]}

    def test_filters_partenaires_without_nom(self):
        meta = _build_source_meta({"partenairesDeRecherche": [{"type": "x"}, {"nom": "LIMOS"}]})
        assert meta == {"partenaires": [{"nom": "LIMOS", "type": None}]}


# ── insert_source_document ───────────────────────────────────────


class TestInsertSourceDocument:
    def _pub_meta(self, **overrides) -> dict:
        base = {
            "title": "T",
            "title_normalized": "t",
            "pub_year": 2024,
            "doc_type": "thesis",
            "doi": None,
            "nnt": None,
            "oa_status": "closed",
            "journal_id": None,
            "container_title": None,
            "language": None,
        }
        base.update(overrides)
        return base

    def _call(self, queries: _FakeQueries, these: dict, *, pub_meta: dict | None = None) -> dict:
        insert_source_document(
            MagicMock(),
            queries,
            these,
            staging_id=1,
            theses_id="2024CLFAC001",
            publication_id=None,
            pub_meta=pub_meta or self._pub_meta(),
        )
        return queries.upserted_documents[-1]

    def test_nnt_goes_in_external_ids(self):
        queries = _FakeQueries()
        captured = self._call(queries, {}, pub_meta=self._pub_meta(nnt="2024CLFAC001"))
        assert captured["external_ids"] == {"nnt": "2024CLFAC001"}

    def test_no_nnt_no_external_ids(self):
        queries = _FakeQueries()
        captured = self._call(queries, {})
        assert captured["external_ids"] is None

    def test_keywords_from_sujets(self):
        queries = _FakeQueries()
        these = {"sujets": [{"libelle": "machine learning"}, {"libelle": "NLP"}, {}]}
        captured = self._call(queries, these)
        assert captured["keywords"] == ["machine learning", "NLP"]

    def test_no_keywords(self):
        queries = _FakeQueries()
        captured = self._call(queries, {})
        assert captured["keywords"] is None

    def test_topics_discipline_only(self):
        queries = _FakeQueries()
        captured = self._call(queries, {"discipline": "Informatique"})
        assert captured["topics_json"] == {"discipline": "Informatique"}

    def test_topics_with_rameau(self):
        queries = _FakeQueries()
        these = {
            "discipline": "Informatique",
            "sujetsRameau": [{"libelle": "Apprentissage automatique"}, {}],
        }
        captured = self._call(queries, these)
        assert captured["topics_json"] == {
            "discipline": "Informatique",
            "rameau": ["Apprentissage automatique"],
        }

    def test_no_topics(self):
        queries = _FakeQueries()
        captured = self._call(queries, {})
        assert captured["topics_json"] is None

    def test_source_meta_passed(self):
        queries = _FakeQueries()
        captured = self._call(queries, {"dateSoutenance": "15/03/2024"})
        assert captured["source_meta_json"] == {"date_soutenance": "2024-03-15"}

    def test_title_empty_string_when_none(self):
        queries = _FakeQueries()
        captured = self._call(queries, {}, pub_meta=self._pub_meta(title=None))
        assert captured["title"] == ""


# ── process_persons ──────────────────────────────────────────────


class TestProcessPersons:
    def test_no_authors_no_upsert(self, monkeypatch):
        monkeypatch.setattr(normalize_theses, "aggregate_thesis_persons", lambda these: [])
        queries = _FakeQueries()
        process_persons(MagicMock(), queries, {}, 10, address_linker=_FakeAddressLinker())
        assert queries.cleared_for == [10]
        assert queries.upserted_authorships == []

    def test_with_authors(self, monkeypatch):
        # Stub aggregate_thesis_persons pour ne pas dépendre du domain.
        class _A:
            def __init__(self, name, pos, roles, ids=None):
                self.raw_author_name = name
                self.author_position = pos
                self.roles = roles
                self.person_identifiers = ids

        monkeypatch.setattr(
            normalize_theses,
            "aggregate_thesis_persons",
            lambda these: [
                _A("DUPONT Marie", 0, ["author"], {"idref": "123"}),
                _A("MARTIN Jean", 1, ["director"]),
            ],
        )
        queries = _FakeQueries()
        process_persons(MagicMock(), queries, {}, 10, address_linker=_FakeAddressLinker())
        assert len(queries.upserted_authorships) == 2
        assert queries.upserted_authorships[0]["person_identifiers"] == {"idref": "123"}
        # `None` quand l'aggregate n'a pas d'identifiants.
        assert queries.upserted_authorships[1]["person_identifiers"] is None

    def test_partenaires_become_addr_parts(self, monkeypatch):
        class _A:
            raw_author_name = "X"
            author_position = 0
            roles = ["author"]
            person_identifiers = None

        monkeypatch.setattr(normalize_theses, "aggregate_thesis_persons", lambda these: [_A()])
        queries = _FakeQueries()
        linker = _FakeAddressLinker()
        these = {"partenairesDeRecherche": [{"nom": "LIMOS"}, {"nom": "LRL"}, {}]}
        process_persons(MagicMock(), queries, these, 10, address_linker=linker)
        assert linker.links == [(101, ["LIMOS", "LRL"])]

    def test_etablissement_appended_to_addr_parts(self, monkeypatch):
        class _A:
            raw_author_name = "X"
            author_position = 0
            roles = ["author"]
            person_identifiers = None

        monkeypatch.setattr(normalize_theses, "aggregate_thesis_persons", lambda these: [_A()])
        queries = _FakeQueries()
        linker = _FakeAddressLinker()
        these = {
            "partenairesDeRecherche": [{"nom": "LIMOS"}],
            "etabSoutenanceN": "Université Clermont Auvergne (2021-...)",
        }
        process_persons(MagicMock(), queries, these, 10, address_linker=linker)
        assert linker.links == [(101, ["LIMOS", "Université Clermont Auvergne (2021-...)"])]

    def test_etablissement_alone_creates_link(self, monkeypatch):
        """Sans partenaire, l'établissement de soutenance suffit à poser une
        adresse (→ rattachement périmètre des thèses)."""

        class _A:
            raw_author_name = "X"
            author_position = 0
            roles = ["author"]
            person_identifiers = None

        monkeypatch.setattr(normalize_theses, "aggregate_thesis_persons", lambda these: [_A()])
        queries = _FakeQueries()
        linker = _FakeAddressLinker()
        these = {"etabSoutenanceN": "Université Clermont Auvergne (2021-...)"}
        process_persons(MagicMock(), queries, these, 10, address_linker=linker)
        assert linker.links == [(101, ["Université Clermont Auvergne (2021-...)"])]

    def test_no_partenaires_no_link(self, monkeypatch):
        class _A:
            raw_author_name = "X"
            author_position = 0
            roles = ["author"]
            person_identifiers = None

        monkeypatch.setattr(normalize_theses, "aggregate_thesis_persons", lambda these: [_A()])
        queries = _FakeQueries()
        linker = _FakeAddressLinker()
        process_persons(MagicMock(), queries, {}, 10, address_linker=linker)
        assert linker.links == []


# ── process_work ─────────────────────────────────────────────────


class TestProcessWork:
    def _kwargs(self, queries=None, staging_queries=None):
        return {
            "queries": queries or _FakeQueries(),
            "logger": logging.getLogger("test"),
            "pub_repo": MagicMock(),
            "staging_queries": staging_queries or _FakeStagingQueries(),
            "address_linker": _FakeAddressLinker(),
        }

    def test_skip_when_no_title(self, caplog):
        row = _staging_row(theses_id="2024CLFAC001", raw={})
        with caplog.at_level(logging.WARNING):
            result = process_work(MagicMock(), row=row, **self._kwargs())
        assert result is False
        assert "sans titre" in caplog.text

    def test_happy_path(self, monkeypatch):
        monkeypatch.setattr(normalize_theses, "aggregate_thesis_persons", lambda these: [])
        sq = _FakeStagingQueries()
        row = _staging_row(staging_id=42, raw={"titrePrincipal": "T"})
        result = process_work(MagicMock(), row=row, **self._kwargs(staging_queries=sq))
        assert result is True
        assert sq.marked_done == [42]

    def test_exception_propagated_and_logged(self, monkeypatch, caplog):
        def boom(*args, **kw):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(normalize_theses, "insert_source_document", boom)
        row = _staging_row(theses_id="hal-x", raw={"titrePrincipal": "T"})
        with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
            process_work(MagicMock(), row=row, **self._kwargs())
        assert "hal-x" in caplog.text and "kaboom" in caplog.text


# ── ThesesNormalizer (classe) ────────────────────────────────────


def _make_normalizer():
    return ThesesNormalizer(
        conn=MagicMock(),
        logger=logging.getLogger("test"),
        staging_queries=_FakeStagingQueries(),
        queries=_FakeQueries(),
        pub_repo_factory=lambda c: MagicMock(),
        address_linker=_FakeAddressLinker(),
    )


class TestThesesNormalizerClass:
    def test_preload_caches_sets_pub_repo(self):
        norm = _make_normalizer()
        norm.preload_caches(MagicMock())
        assert norm._pub_repo is not None

    def test_process_work_delegates(self, monkeypatch):
        norm = _make_normalizer()
        norm.preload_caches(MagicMock())
        monkeypatch.setattr(normalize_theses, "process_work", lambda *a, **kw: True)
        result = norm.process_work(MagicMock(), _staging_row())
        assert result is True

    def test_cleanup_clears_address_linker_cache(self):
        norm = _make_normalizer()
        norm.cleanup()
        assert norm._address_linker.cleared == 1  # type: ignore[attr-defined]

    def test_on_error_clears_address_linker_cache(self):
        norm = _make_normalizer()
        norm.on_error()
        assert norm._address_linker.cleared == 1  # type: ignore[attr-defined]

    def test_summary_stats_returns_2_lines(self):
        norm = _make_normalizer()
        norm._queries.count_table_returns = {  # type: ignore[attr-defined]
            "source_publications": 100,
            "source_authorships": 250,
        }
        lines = norm.summary_stats(MagicMock())
        assert len(lines) == 2
        assert "100" in lines[0]
        assert "250" in lines[1]
