"""Tests unitaires de `pipeline.sources.theses.normalize`.

Couvre `extract_pub_metadata` (cascade pub_year soutenance/inscription, NNT, doc_type), `_build_source_meta` (date_soutenance, date_inscription, discipline, écoles doctorales, partenaires), `insert_source_document` (keywords sujets, topics discipline+rameau, NNT external_ids), `build_theses_author_records` (rôles, positions, adresses du document), `process_authorships` (writer partagé, renormalisation), `process_work` (skip sans titre, happy path, exception), et la classe `ThesesNormalizer` (preload, process_work wrapper, summary_stats).

Pattern : `FakeSourcePublicationQueries` + `MagicMock`, pas de DB.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from pipeline.sources.pub_metadata import PublicationMetadata
from pipeline.sources.signatures import SignatureSyncSettings
from pipeline.sources.theses import normalize as normalize_theses
from pipeline.sources.theses.normalize import (
    ThesesNormalizer,
    _build_source_meta,
    build_theses_author_records,
    extract_pub_metadata,
    extract_theses_author_block,
    insert_source_document,
    process_authorships,
    process_work,
)
from tests.helpers.normalize_doubles import (
    FakeAuthorshipsBatchQueries,
    FakeSourcePublicationQueries,
    FakeStagingQueries,
    staging_row,
)

# ── extract_pub_metadata ─────────────────────────────────────────


class TestExtractPubMetadata:
    def test_minimal(self):
        meta = extract_pub_metadata({"titrePrincipal": "T"})
        assert meta.title == "T"
        assert meta.pub_year is None
        assert meta.nnt is None
        assert meta.oa_status == "closed"
        assert meta.journal_id is None

    def test_pub_year_from_soutenance(self):
        meta = extract_pub_metadata({"titrePrincipal": "T", "dateSoutenance": "15/03/2024"})
        assert meta.pub_year == 2024

    def test_pub_year_fallback_to_inscription(self):
        """Si pas de date_soutenance, on prend date_inscription."""
        meta = extract_pub_metadata(
            {"titrePrincipal": "T", "datePremiereInscriptionDoctorat": "10/09/2020"}
        )
        assert meta.pub_year == 2020

    def test_pub_year_soutenance_wins_over_inscription(self):
        meta = extract_pub_metadata(
            {
                "titrePrincipal": "T",
                "dateSoutenance": "15/03/2024",
                "datePremiereInscriptionDoctorat": "10/09/2020",
            }
        )
        assert meta.pub_year == 2024

    def test_no_title(self):
        meta = extract_pub_metadata({})
        assert meta.title is None

    def test_nnt_normalized(self):
        meta = extract_pub_metadata({"titrePrincipal": "T", "nnt": "  2024clfac001  "})
        assert meta.nnt == "2024CLFAC001"

    def test_doi_passthrough(self):
        meta = extract_pub_metadata({"titrePrincipal": "T", "doi": "10.1/abc"})
        assert meta.doi == "10.1/abc"


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
    def _pub_meta(self, **overrides) -> PublicationMetadata:
        base: dict[str, Any] = {
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
        return PublicationMetadata(**base)

    def _call(
        self,
        queries: FakeSourcePublicationQueries,
        these: dict,
        *,
        pub_meta: PublicationMetadata | None = None,
    ) -> dict:
        insert_source_document(
            MagicMock(),
            queries,
            these,
            staging_id=1,
            theses_id="2024CLFAC001",
            pub_meta=pub_meta or self._pub_meta(),
        )
        return queries.upserted_documents[-1]

    def test_nnt_goes_in_external_ids(self):
        queries = FakeSourcePublicationQueries()
        captured = self._call(queries, {}, pub_meta=self._pub_meta(nnt="2024CLFAC001"))
        assert captured.external_ids == {"nnt": "2024CLFAC001"}

    def test_no_nnt_no_external_ids(self):
        queries = FakeSourcePublicationQueries()
        captured = self._call(queries, {})
        assert captured.external_ids is None

    def test_keywords_from_sujets(self):
        queries = FakeSourcePublicationQueries()
        these = {"sujets": [{"libelle": "machine learning"}, {"libelle": "NLP"}, {}]}
        captured = self._call(queries, these)
        assert captured.keywords == ["machine learning", "NLP"]

    def test_no_keywords(self):
        queries = FakeSourcePublicationQueries()
        captured = self._call(queries, {})
        assert captured.keywords is None

    def test_topics_discipline_only(self):
        queries = FakeSourcePublicationQueries()
        captured = self._call(queries, {"discipline": "Informatique"})
        assert captured.topics == {"discipline": "Informatique"}

    def test_topics_with_rameau(self):
        queries = FakeSourcePublicationQueries()
        these = {
            "discipline": "Informatique",
            "sujetsRameau": [{"libelle": "Apprentissage automatique"}, {}],
        }
        captured = self._call(queries, these)
        assert captured.topics == {
            "discipline": "Informatique",
            "rameau": ["Apprentissage automatique"],
        }

    def test_no_topics(self):
        queries = FakeSourcePublicationQueries()
        captured = self._call(queries, {})
        assert captured.topics is None

    def test_source_meta_passed(self):
        queries = FakeSourcePublicationQueries()
        captured = self._call(queries, {"dateSoutenance": "15/03/2024"})
        assert captured.meta == {"date_soutenance": "2024-03-15"}

    def test_title_empty_string_when_none(self):
        queries = FakeSourcePublicationQueries()
        captured = self._call(queries, {}, pub_meta=self._pub_meta(title=None))
        assert captured.title == ""


# ── process_authorships ──────────────────────────────────────────────


_SYNC = SignatureSyncSettings(fingerprint=lambda content: json.dumps(content, sort_keys=True))


def _these(**fields):
    """Thèse avec un auteur (IdRef connu) et un directeur."""
    return {
        "auteurs": [{"nom": "Dupont", "prenom": "Marie", "ppn": "123"}],
        "directeurs": [{"nom": "Martin", "prenom": "Jean"}],
        **fields,
    }


class TestBuildThesesAuthorRecords:
    def test_seuls_les_auteurs_ont_une_position(self):
        records = build_theses_author_records(extract_theses_author_block(_these()))
        assert [(r.position, r.roles, r.person_identifiers) for r in records] == [
            (0, ["author"], {"idref": "123"}),
            (None, ["thesis_director"], None),
        ]

    def test_adresses_du_document_pour_chaque_signature(self):
        """Partenaires et établissement de soutenance : l'établissement rattache la thèse au périmètre."""
        these = _these(
            partenairesDeRecherche=[{"nom": "LIMOS"}, {}],
            etabSoutenanceN="Université Clermont Auvergne (2021-...)",
        )
        records = build_theses_author_records(extract_theses_author_block(these))
        assert {tuple(a.text for a in r.addresses) for r in records} == {
            ("LIMOS", "Université Clermont Auvergne (2021-...)")
        }

    def test_sans_partenaire_ni_etablissement_aucune_adresse(self):
        records = build_theses_author_records(extract_theses_author_block(_these()))
        assert all(r.addresses == [] for r in records)


class TestProcessAuthorships:
    def test_signatures_ecrites_par_le_writer_partage(self):
        batch = FakeAuthorshipsBatchQueries()
        process_authorships(MagicMock(), _these(), 10, batch_queries=batch, sync_settings=_SYNC)
        assert batch.synced_for == [10]
        assert [v["author_position"] for v in batch.upserted_batches[0]] == [0, None]

    def test_renormalisation_garde_les_signatures(self):
        """Une thèse modifiée garde l'identifiant des signatures dont l'identité ne change pas, directeur compris."""
        batch = FakeAuthorshipsBatchQueries()
        process_authorships(MagicMock(), _these(), 10, batch_queries=batch, sync_settings=_SYNC)
        modified = _these(rapporteurs=[{"nom": "Durand", "prenom": "Paul"}])
        process_authorships(MagicMock(), modified, 10, batch_queries=batch, sync_settings=_SYNC)
        assert [len(b) for b in batch.upserted_batches] == [2, 1]
        assert batch.upserted_batches[1][0]["raw_last_name"] == "Durand"


# ── process_work ─────────────────────────────────────────────────


class TestProcessWork:
    def _kwargs(self, queries=None, staging_queries=None):
        return {
            "queries": queries or FakeSourcePublicationQueries(),
            "logger": logging.getLogger("test"),
            "staging_queries": staging_queries or FakeStagingQueries(),
            "batch_queries": MagicMock(),
            "sync_settings": _SYNC,
        }

    def test_happy_path(self, monkeypatch):
        monkeypatch.setattr(normalize_theses, "aggregate_thesis_persons", lambda these: [])
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
        queries=FakeSourcePublicationQueries(),
        batch_queries=MagicMock(),
        sync_settings=_SYNC,
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
