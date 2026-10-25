"""Moissonnage HAL (`pipeline.ingestion.hal.harvest`).

Requêtes Solr et champs des enregistrements sources : fonctions pures. Pilotage par `HalHarvester` : découpage en périmètres temporels, comptage préalable de chaque périmètre, mode incrémental, refus d'une configuration sans collection, arrêt sur disjoncteur. Pas de réseau ni de base : un faux client sert une page vide, la lecture de la configuration est remplacée, la connexion est un mock.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from pipeline.ingestion.common import harvester as common_harvest
from pipeline.ingestion.common.harvester import HarvestConfigError
from pipeline.ingestion.hal import harvest
from pipeline.ingestion.hal.fields import extract_doi, extract_id
from pipeline.ingestion.hal.harvest import HalHarvester, build_collections_fq, build_query
from tests.helpers.harvesters import arguments_du_run

_LOGGER = logging.getLogger("test")

# Page Solr close : aucun document, marqueur inchangé — la pagination s'arrête au premier tour.
_PAGE_VIDE = {"response": {"numFound": 0, "docs": []}, "nextCursorMark": "*"}


class TestBuildQuery:
    def test_combines_years_and_since(self):
        assert build_query(years=[2024, 2026], since="2026-05-01") == (
            "producedDateY_i:[2024 TO 2026] AND modifiedDate_tdate:[2026-05-01T00:00:00Z TO *]"
        )

    def test_since_alone(self):
        assert build_query(years=None, since="2025-12-31") == (
            "modifiedDate_tdate:[2025-12-31T00:00:00Z TO *]"
        )

    def test_years_range_uses_min_and_max(self):
        assert build_query(years=[2023, 2026, 2024]) == "producedDateY_i:[2023 TO 2026]"

    def test_raises_when_no_filter(self):
        with pytest.raises(ValueError):
            build_query(years=None)
        with pytest.raises(ValueError):
            build_query(years=[])


class TestBuildCollectionsFq:
    def test_union_joined_with_or_and_quoted(self):
        # Les codes sont entre guillemets : un tiret serait sinon lu comme un opérateur Solr.
        assert build_collections_fq(["LIMOS", "CHU-CLERMONTFERRAND"]) == (
            'collCode_s:("LIMOS" OR "CHU-CLERMONTFERRAND")'
        )


class TestFields:
    def test_extract_id(self):
        assert extract_id({"halId_s": "hal-12345"}) == "hal-12345"
        assert extract_id({}) == ""

    def test_extract_doi(self):
        assert extract_doi({"doiId_s": "https://doi.org/10.1000/abc"}) == "10.1000/abc"
        assert extract_doi({"doiId_s": ["10.1000/abc"]}) == "10.1000/abc"
        assert extract_doi({}) is None
        assert extract_doi({"doiId_s": ""}) is None


@pytest.fixture
def configuration(monkeypatch):
    """Remplace la lecture des collections et des années en base."""

    def _poser(collections: dict[str, str], annees: list[int]) -> None:
        monkeypatch.setattr(harvest, "get_hal_collections", lambda conn: collections)
        monkeypatch.setattr(
            common_harvest,
            "window_years",
            lambda conn, *, start_year, year: [year] if year else annees,
        )

    return _poser


def _client() -> MagicMock:
    client = MagicMock()
    client.count.return_value = 0
    client.fetch_page_cursor.return_value = _PAGE_VIDE
    return client


def test_une_passe_par_annee_de_la_configuration(configuration):
    configuration({"C": "Coll"}, [2023, 2024])
    client = _client()
    HalHarvester(MagicMock(), _LOGGER, client).run(arguments_du_run())
    requetes = [appel.args[0] for appel in client.fetch_page_cursor.call_args_list]
    assert requetes == [build_query(years=[2023]), build_query(years=[2024])]


def test_chaque_annee_est_comptee_avant_l_extraction(configuration):
    configuration({"C": "Coll"}, [2023, 2024])
    client = _client()
    HalHarvester(MagicMock(), _LOGGER, client).run(arguments_du_run())
    fq = build_collections_fq(["C"])
    comptees = [appel.args for appel in client.count.call_args_list]
    assert comptees == [(build_query(years=[2023]), fq), (build_query(years=[2024]), fq)]


def test_une_annee_demandee_ignore_la_configuration(configuration):
    configuration({"C": "Coll"}, [2020, 2021])
    client = _client()
    HalHarvester(MagicMock(), _LOGGER, client).run(arguments_du_run(year=2024))
    assert client.fetch_page_cursor.call_args.args[0] == build_query(years=[2024])


def test_mode_incremental_fait_une_seule_passe_sur_la_date(configuration):
    configuration({"C": "Coll"}, [2020, 2021, 2022])
    client = _client()
    HalHarvester(MagicMock(), _LOGGER, client).run(arguments_du_run(since="2026-01-01"))
    assert client.fetch_page_cursor.call_count == 1


def test_mode_incremental_garde_les_annees_du_mode_complet(configuration):
    # Un enregistrement source ancienne modifiée depuis la date reste hors de la plage d'années.
    configuration({"C": "Coll"}, [2020, 2021, 2022])
    client = _client()
    HalHarvester(MagicMock(), _LOGGER, client).run(arguments_du_run(since="2026-01-01"))
    attendue = build_query(years=[2020, 2021, 2022], since="2026-01-01")
    assert client.count.call_args.args[0] == attendue
    assert client.fetch_page_cursor.call_args.args[0] == attendue


def test_sans_collection_refuse(configuration):
    configuration({}, [2024])
    with pytest.raises(HarvestConfigError, match="aucune collection HAL"):
        HalHarvester(MagicMock(), _LOGGER, _client()).run(arguments_du_run())
