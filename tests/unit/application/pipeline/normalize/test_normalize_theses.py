"""Tests unitaires de `application.pipeline.normalize.normalize_theses`.

Couvre `extract_pub_metadata` (cascade pub_year soutenance/inscription, NNT, doc_type), `_build_source_meta` (date_soutenance, date_inscription, discipline, écoles doctorales, partenaires), `insert_source_document` (keywords sujets, topics discipline+rameau, NNT external_ids), `process_authorships` (aggregate_thesis_persons, partenaires + établissement → adresses partagées), `process_work` (skip sans titre, happy path, exception), et la classe `ThesesNormalizer` (preload, process_work wrapper, summary_stats).

Pattern : `_FakeQueries` + `MagicMock`, pas de DB.
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
    process_authorships,
    process_work,
)
from application.ports.pipeline.normalize.staging import StagingRow

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

    def test_no_title(self):
        meta = extract_pub_metadata({})
        assert meta["title"] is None

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


# ── process_authorships ──────────────────────────────────────────────


def _spy_write_addresses(monkeypatch):
    """Espion sur `write_addresses` capturant les `sa_addresses` de chaque appel."""
    calls: list[list[tuple[int | None, list]]] = []
    monkeypatch.setattr(
        normalize_theses,
        "write_addresses",
        lambda conn, batch_queries, sa_addresses: calls.append(sa_addresses),
    )
    return calls


def _addr_texts(sa_addresses):
    """Aplati les `sa_addresses` capturés en `(sa_id, [texte, ...])` pour les assertions."""
    return [(sa_id, [a.text for a in addrs]) for sa_id, addrs in sa_addresses]


class _Author:
    def __init__(self, name="X", pos=0, roles=None, ids=None):
        self.raw_author_name = name
        self.author_position = pos
        self.roles = roles or ["author"]
        self.person_identifiers = ids


class TestProcessPersons:
    def test_no_authors_no_upsert(self, monkeypatch):
        monkeypatch.setattr(normalize_theses, "aggregate_thesis_persons", lambda these: [])
        calls = _spy_write_addresses(monkeypatch)
        queries = _FakeQueries()
        process_authorships(MagicMock(), queries, {}, 10, batch_queries=MagicMock())
        assert queries.cleared_for == [10]
        assert queries.upserted_authorships == []
        assert calls == []

    def test_with_authors(self, monkeypatch):
        monkeypatch.setattr(
            normalize_theses,
            "aggregate_thesis_persons",
            lambda these: [
                _Author("DUPONT Marie", 0, ["author"], {"idref": "123"}),
                _Author("MARTIN Jean", 1, ["director"]),
            ],
        )
        _spy_write_addresses(monkeypatch)
        queries = _FakeQueries()
        process_authorships(MagicMock(), queries, {}, 10, batch_queries=MagicMock())
        assert len(queries.upserted_authorships) == 2
        assert queries.upserted_authorships[0]["person_identifiers"] == {"idref": "123"}
        # `None` quand l'aggregate n'a pas d'identifiants.
        assert queries.upserted_authorships[1]["person_identifiers"] is None

    def test_partenaires_become_addr_parts(self, monkeypatch):
        monkeypatch.setattr(normalize_theses, "aggregate_thesis_persons", lambda these: [_Author()])
        calls = _spy_write_addresses(monkeypatch)
        queries = _FakeQueries()
        these = {"partenairesDeRecherche": [{"nom": "LIMOS"}, {"nom": "LRL"}, {}]}
        process_authorships(MagicMock(), queries, these, 10, batch_queries=MagicMock())
        assert _addr_texts(calls[0]) == [(101, ["LIMOS", "LRL"])]

    def test_etablissement_appended_to_addr_parts(self, monkeypatch):
        monkeypatch.setattr(normalize_theses, "aggregate_thesis_persons", lambda these: [_Author()])
        calls = _spy_write_addresses(monkeypatch)
        queries = _FakeQueries()
        these = {
            "partenairesDeRecherche": [{"nom": "LIMOS"}],
            "etabSoutenanceN": "Université Clermont Auvergne (2021-...)",
        }
        process_authorships(MagicMock(), queries, these, 10, batch_queries=MagicMock())
        assert _addr_texts(calls[0]) == [
            (101, ["LIMOS", "Université Clermont Auvergne (2021-...)"])
        ]

    def test_etablissement_alone_creates_link(self, monkeypatch):
        """Sans partenaire, l'établissement de soutenance suffit à poser une adresse (→ rattachement périmètre des thèses)."""
        monkeypatch.setattr(normalize_theses, "aggregate_thesis_persons", lambda these: [_Author()])
        calls = _spy_write_addresses(monkeypatch)
        queries = _FakeQueries()
        these = {"etabSoutenanceN": "Université Clermont Auvergne (2021-...)"}
        process_authorships(MagicMock(), queries, these, 10, batch_queries=MagicMock())
        assert _addr_texts(calls[0]) == [(101, ["Université Clermont Auvergne (2021-...)"])]

    def test_no_partenaires_no_link(self, monkeypatch):
        monkeypatch.setattr(normalize_theses, "aggregate_thesis_persons", lambda these: [_Author()])
        calls = _spy_write_addresses(monkeypatch)
        queries = _FakeQueries()
        process_authorships(MagicMock(), queries, {}, 10, batch_queries=MagicMock())
        assert calls == []


# ── process_work ─────────────────────────────────────────────────


class TestProcessWork:
    def _kwargs(self, queries=None, staging_queries=None):
        return {
            "queries": queries or _FakeQueries(),
            "logger": logging.getLogger("test"),
            "pub_repo": MagicMock(),
            "staging_queries": staging_queries or _FakeStagingQueries(),
            "batch_queries": MagicMock(),
        }

    def test_skip_when_no_title(self, caplog):
        sq = _FakeStagingQueries()
        row = _staging_row(staging_id=7, theses_id="2024CLFAC001", raw={})
        with caplog.at_level(logging.WARNING):
            result = process_work(MagicMock(), staging_row=row, **self._kwargs(staging_queries=sq))
        assert result is False
        assert "sans titre" in caplog.text
        # Marquée traitée pour ne pas retenter indéfiniment une thèse sans titre.
        assert sq.marked_done == [7]

    def test_happy_path(self, monkeypatch):
        monkeypatch.setattr(normalize_theses, "aggregate_thesis_persons", lambda these: [])
        sq = _FakeStagingQueries()
        row = _staging_row(staging_id=42, raw={"titrePrincipal": "T"})
        result = process_work(MagicMock(), staging_row=row, **self._kwargs(staging_queries=sq))
        assert result is True
        assert sq.marked_done == [42]

    def test_exception_propagated(self, monkeypatch):
        """process_work laisse remonter l'exception ; le log incombe à la boucle de base."""

        def boom(*args, **kw):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(normalize_theses, "insert_source_document", boom)
        row = _staging_row(theses_id="hal-x", raw={"titrePrincipal": "T"})
        with pytest.raises(RuntimeError, match="kaboom"):
            process_work(MagicMock(), staging_row=row, **self._kwargs())


# ── ThesesNormalizer (classe) ────────────────────────────────────


def _make_normalizer():
    return ThesesNormalizer(
        conn=MagicMock(),
        logger=logging.getLogger("test"),
        staging_queries=_FakeStagingQueries(),
        queries=_FakeQueries(),
        pub_repo_factory=lambda c: MagicMock(),
        batch_queries=MagicMock(),
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
