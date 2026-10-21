"""Tests unitaires de `pipeline.ingestion.theses.normalize`.

Couvre `extract_publication_metadata` (cascade publication_year soutenance/inscription, NNT, doc_type), `_build_source_extras` (date_soutenance, date_inscription, discipline, écoles doctorales, partenaires), `insert_source_document` (keywords sujets, topics discipline+rameau, NNT external_ids), `build_theses_author_records` (rôles, positions, adresses du document), `process_contributions` (writer partagé, renormalisation), `process_work` (skip sans titre, happy path, exception), et la classe `ThesesNormalizer` (preload, process_work wrapper, summary_stats).

Pattern : `FakeSourceRecordQueries` + `MagicMock`, pas de DB.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from pipeline.ingestion.common.publication_metadata import PublicationMetadata
from pipeline.ingestion.theses import normalize as normalize_theses
from pipeline.ingestion.theses.normalize import (
    ThesesNormalizer,
    _build_source_extras,
    build_theses_author_records,
    extract_publication_metadata,
    extract_theses_author_block,
    insert_source_document,
    process_contributions,
    process_work,
)
from tests.helpers.normalize_doubles import (
    FakeSourceContributionStore,
    FakeSourceRecordQueries,
    FakeStagingQueries,
    staging_row,
)

# ── extract_publication_metadata ─────────────────────────────────────────


class TestExtractPublicationMetadata:
    def test_minimal(self):
        meta = extract_publication_metadata({"titrePrincipal": "T"})
        assert meta.title == "T"
        assert meta.publication_year is None
        assert meta.nnt is None
        assert meta.oa_status == "closed"
        assert meta.journal_id is None

    def test_publication_year_from_soutenance(self):
        meta = extract_publication_metadata({"titrePrincipal": "T", "dateSoutenance": "15/03/2024"})
        assert meta.publication_year == 2024

    def test_publication_year_fallback_to_inscription(self):
        """Si pas de date_soutenance, on prend date_inscription."""
        meta = extract_publication_metadata(
            {"titrePrincipal": "T", "datePremiereInscriptionDoctorat": "10/09/2020"}
        )
        assert meta.publication_year == 2020

    def test_publication_year_soutenance_wins_over_inscription(self):
        meta = extract_publication_metadata(
            {
                "titrePrincipal": "T",
                "dateSoutenance": "15/03/2024",
                "datePremiereInscriptionDoctorat": "10/09/2020",
            }
        )
        assert meta.publication_year == 2024

    def test_no_title(self):
        meta = extract_publication_metadata({})
        assert meta.title is None

    def test_nnt_normalized(self):
        meta = extract_publication_metadata({"titrePrincipal": "T", "nnt": "  2024clfac001  "})
        assert meta.nnt == "2024CLFAC001"

    def test_doi_passthrough(self):
        meta = extract_publication_metadata({"titrePrincipal": "T", "doi": "10.1/abc"})
        assert meta.doi == "10.1/abc"


# ── _build_source_extras ───────────────────────────────────────────


class TestBuildSourceMeta:
    def test_empty(self):
        assert _build_source_extras({}) is None

    def test_only_soutenance(self):
        meta = _build_source_extras({"dateSoutenance": "15/03/2024"})
        assert meta == {"date_soutenance": "2024-03-15"}

    def test_etablissement(self):
        meta = _build_source_extras(
            {
                "etabSoutenanceN": "Université Clermont Auvergne (2021-...)",
                "etabSoutenancePpn": "252404955",
            }
        )
        assert meta == {
            "etablissement": "Université Clermont Auvergne (2021-...)",
            "etablissement_ppn": "252404955",
        }

    def test_full(self):
        thesis = {
            "dateSoutenance": "15/03/2024",
            "datePremiereInscriptionDoctorat": "10/09/2020",
            "discipline": "Informatique",
            "etabSoutenanceN": "Université Clermont Auvergne (2021-...)",
            "ecolesDoctorale": [{"nom": "EDSPI", "ppn": "1234"}, {"nom": "EDMS"}],
            "partenairesDeRecherche": [
                {"nom": "LIMOS", "type": "labo", "ppn": "035163569"},
                {"nom": "LRL"},
            ],
        }
        meta = _build_source_extras(thesis)
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
            {"nom": "LIMOS", "type": "labo", "ppn": "035163569"},
            {"nom": "LRL", "type": None, "ppn": None},
        ]

    def test_filters_ecoles_without_nom(self):
        meta = _build_source_extras({"ecolesDoctorale": [{"ppn": "123"}, {"nom": "EDSPI"}]})
        assert meta == {"ecoles_doctorales": [{"nom": "EDSPI", "ppn": None}]}

    def test_filters_partenaires_without_nom(self):
        meta = _build_source_extras({"partenairesDeRecherche": [{"type": "x"}, {"nom": "LIMOS"}]})
        assert meta == {"partenaires": [{"nom": "LIMOS", "type": None, "ppn": None}]}


# ── insert_source_document ───────────────────────────────────────


class TestInsertSourceDocument:
    def _publication_meta(self, **overrides) -> PublicationMetadata:
        base: dict[str, Any] = {
            "title": "T",
            "publication_year": 2024,
            "doc_type": "thesis",
            "doi": None,
            "nnt": None,
            "oa_status": "closed",
            "journal_id": None,
            "container_title": None,
            "language": None,
        }
        base.update(overrides)
        return PublicationMetadata(**base)

    def _call(
        self,
        queries: FakeSourceRecordQueries,
        thesis: dict,
        *,
        publication_meta: PublicationMetadata | None = None,
    ) -> dict:
        insert_source_document(
            MagicMock(),
            queries,
            thesis,
            staging_id=1,
            theses_id="2024CLFAC001",
            publication_meta=publication_meta or self._publication_meta(),
        )
        return queries.upserted_documents[-1]

    def test_nnt_goes_in_external_ids(self):
        queries = FakeSourceRecordQueries()
        captured = self._call(
            queries, {}, publication_meta=self._publication_meta(nnt="2024CLFAC001")
        )
        assert captured.external_ids == {"nnt": "2024CLFAC001"}

    def test_no_nnt_no_external_ids(self):
        queries = FakeSourceRecordQueries()
        captured = self._call(queries, {})
        assert captured.external_ids is None

    def test_keywords_from_sujets(self):
        queries = FakeSourceRecordQueries()
        thesis = {"sujets": [{"libelle": "machine learning"}, {"libelle": "NLP"}, {}]}
        captured = self._call(queries, thesis)
        assert captured.keywords == ["machine learning", "NLP"]

    def test_no_keywords(self):
        queries = FakeSourceRecordQueries()
        captured = self._call(queries, {})
        assert captured.keywords is None

    def test_topics_discipline_only(self):
        queries = FakeSourceRecordQueries()
        captured = self._call(queries, {"discipline": "Informatique"})
        assert captured.topics == {"discipline": "Informatique"}

    def test_topics_with_rameau(self):
        queries = FakeSourceRecordQueries()
        thesis = {
            "discipline": "Informatique",
            "sujetsRameau": [{"libelle": "Apprentissage automatique"}, {}],
        }
        captured = self._call(queries, thesis)
        assert captured.topics == {
            "discipline": "Informatique",
            "rameau": ["Apprentissage automatique"],
        }

    def test_no_topics(self):
        queries = FakeSourceRecordQueries()
        captured = self._call(queries, {})
        assert captured.topics is None

    def test_source_meta_passed(self):
        queries = FakeSourceRecordQueries()
        captured = self._call(queries, {"dateSoutenance": "15/03/2024"})
        assert captured.source_extras == {"date_soutenance": "2024-03-15"}

    def test_title_empty_string_when_none(self):
        queries = FakeSourceRecordQueries()
        captured = self._call(queries, {}, publication_meta=self._publication_meta(title=None))
        assert captured.title == ""


# ── process_contributions ──────────────────────────────────────────────


def _these(**fields):
    """Thèse avec un auteur (IdRef connu) et un directeur."""
    return {
        "auteurs": [{"nom": "Dupont", "prenom": "Marie", "ppn": "123456789"}],
        "directeurs": [{"nom": "Martin", "prenom": "Jean"}],
        **fields,
    }


class TestBuildThesesAuthorRecords:
    def test_seuls_les_auteurs_ont_une_position(self):
        records = build_theses_author_records(extract_theses_author_block(_these()))
        assert [(r.position, r.roles, r.identifiers) for r in records] == [
            (0, ["author"], {"idref": "123456789"}),
            (None, ["thesis_director"], None),
        ]

    def test_aucune_adresse(self):
        """Partenaires et établissement de soutenance restent dans `meta` : aucune contribution source ne reçoit d'adresse."""
        thesis = _these(
            partenairesDeRecherche=[{"nom": "LIMOS"}],
            etabSoutenanceN="Université Clermont Auvergne (2021-...)",
        )
        records = build_theses_author_records(extract_theses_author_block(thesis))
        assert all(r.addresses == [] for r in records)


class TestProcessContributions:
    def test_contributions_sources_ecrites_par_le_writer_partage(self):
        batch = FakeSourceContributionStore()
        process_contributions(MagicMock(), _these(), 10, contribution_store=batch)
        assert batch.synced_for == [10]
        assert [v["author_position"] for v in batch.upserted_batches[0]] == [0, None]

    def test_renormalisation_garde_les_contributions_sources(self):
        """Une thèse modifiée garde l'identifiant des contributions sources dont les informations du contributeur restent les mêmes, directeur compris."""
        batch = FakeSourceContributionStore()
        process_contributions(MagicMock(), _these(), 10, contribution_store=batch)
        modified = _these(rapporteurs=[{"nom": "Durand", "prenom": "Paul"}])
        process_contributions(MagicMock(), modified, 10, contribution_store=batch)
        assert [len(b) for b in batch.upserted_batches] == [2, 1]
        assert batch.upserted_batches[1][0]["raw_last_name"] == "Durand"


# ── process_work ─────────────────────────────────────────────────


class TestProcessWork:
    def _kwargs(self, queries=None, staging_queries=None):
        return {
            "queries": queries or FakeSourceRecordQueries(),
            "staging_queries": staging_queries or FakeStagingQueries(),
            "contribution_store": MagicMock(),
        }

    def test_happy_path(self, monkeypatch):
        monkeypatch.setattr(normalize_theses, "aggregate_thesis_persons", lambda thesis: [])
        sq = FakeStagingQueries()
        row = staging_row(staging_id=42, raw={"titrePrincipal": "T"})
        result = process_work(MagicMock(), staging_row=row, **self._kwargs(staging_queries=sq))
        assert result is True
        assert sq.marked_done == [42]

    def test_exception_propagated(self, monkeypatch):
        """process_work laisse remonter l'exception ; le log incombe à la boucle de base."""

        def boom(*args, **kw):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(normalize_theses, "insert_source_document", boom)
        row = staging_row(source_id="hal-x", raw={"titrePrincipal": "T"})
        with pytest.raises(RuntimeError, match="kaboom"):
            process_work(MagicMock(), staging_row=row, **self._kwargs())


# ── ThesesNormalizer (classe) ────────────────────────────────────


def _make_normalizer():
    return ThesesNormalizer(
        conn=MagicMock(),
        logger=logging.getLogger("test"),
        staging_queries=FakeStagingQueries(),
        queries=FakeSourceRecordQueries(),
        contribution_store=MagicMock(),
    )


class TestThesesNormalizerClass:
    def test_metadonnees_minimales(self):
        assert _make_normalizer().minimal_metadata(staging_row(raw={})) == (None, None)

    def test_process_work_delegates(self, monkeypatch):
        norm = _make_normalizer()
        norm.preload_caches(MagicMock())
        monkeypatch.setattr(normalize_theses, "process_work", lambda *a, **kw: True)
        result = norm.normalize_record(MagicMock(), staging_row())
        assert result is True
