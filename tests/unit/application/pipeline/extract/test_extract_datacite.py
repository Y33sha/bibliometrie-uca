"""Tests unitaires de l'orchestrateur d'extraction DataCite et de sa requête.

Pas de réseau ni de base : un faux `DataciteExtractAdapter` sert des pages scriptées, et la connexion est un mock dont seul `commit` est appelé. Ce qui est éprouvé ici est le pilotage — pagination par curseur jusqu'à la dernière page, cumul des comptes rendus par l'upsert, refus d'une configuration sans mot-clé — et la forme de la requête.
"""

from __future__ import annotations

import argparse
import logging
from unittest.mock import MagicMock

import pytest

from application.pipeline.extract.base import ExtractionConfigError
from application.pipeline.extract.extract_datacite import DataciteExtractor
from application.ports.pipeline.circuit_breaker import SourceUnavailableError
from application.ports.pipeline.extract._common import BatchInsertCounts
from application.ports.pipeline.extract.datacite import DataciteExtractConfig, DatacitePage
from infrastructure.sources.datacite.extract_datacite import build_query

_LOGGER = logging.getLogger("test")
_CONFIG = DataciteExtractConfig(keywords=["Clermont", "Auvergne"])


def _adapter(pages: list[DatacitePage]) -> MagicMock:
    a = MagicMock()
    a.count.return_value = sum(len(p.records) for p in pages)
    a.fetch_page.side_effect = pages
    a.insert_batch.side_effect = lambda conn, records: BatchInsertCounts(
        new=len(records), updated=0, unchanged=0
    )
    return a


def _extract(adapter: MagicMock, year: int = 2024):
    extractor = DataciteExtractor(MagicMock(), _LOGGER, adapter)
    return extractor.extract_all(argparse.Namespace(year=year, start_year=None), _CONFIG)


def test_suit_le_curseur_jusqu_a_la_derniere_page():
    adapter = _adapter(
        [
            DatacitePage(records=[{"id": "10.1/a"}, {"id": "10.1/b"}], next_url="https://next/1"),
            DatacitePage(records=[{"id": "10.1/c"}], next_url=None),
        ]
    )
    metrics = _extract(adapter)

    assert metrics.new == 3
    assert [c.args[2] for c in adapter.fetch_page.call_args_list] == [None, "https://next/1"]


def test_une_erreur_d_annee_n_interrompt_pas_le_bilan():
    adapter = _adapter([])
    adapter.fetch_page.side_effect = RuntimeError("API indisponible")
    assert _extract(adapter).new == 0


def test_source_indisponible_saute_les_annees_suivantes():
    adapter = _adapter([])
    adapter.get_years.return_value = [2023, 2024]
    adapter.fetch_page.side_effect = SourceUnavailableError("datacite")
    extractor = DataciteExtractor(MagicMock(), _LOGGER, adapter)
    metrics = extractor.extract_all(argparse.Namespace(year=None, start_year=None), _CONFIG)
    assert metrics.total == 0
    assert adapter.fetch_page.call_count == 1


def test_configuration_sans_mot_cle_refusee():
    adapter = MagicMock()
    adapter.load_config.return_value = DataciteExtractConfig(keywords=[])
    with pytest.raises(ExtractionConfigError):
        DataciteExtractor(MagicMock(), _LOGGER, adapter).load_config(MagicMock())


def test_requete_par_annee_et_mots_cles():
    assert build_query(2024, ["Clermont", "Univ. Clermont Auvergne"]) == (
        'publicationYear:2024 AND (creators.affiliation.name:"Clermont" '
        'OR creators.affiliation.name:"Univ. Clermont Auvergne")'
    )


def test_guillemets_d_un_mot_cle_echappes():
    assert build_query(2024, ['Labo "X"']) == (
        'publicationYear:2024 AND (creators.affiliation.name:"Labo \\"X\\"")'
    )
