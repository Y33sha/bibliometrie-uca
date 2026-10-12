"""Moissonnage DataCite (`pipeline.sources.datacite.harvest`).

Requête : fonction pure. Pilotage : pagination par curseur jusqu'à la dernière page, isolement de l'échec d'une année, arrêt sur source indisponible, refus d'une configuration sans mot-clé. Pas de réseau ni de base : un faux client sert des pages scriptées, la configuration et l'écriture dans `staging` sont remplacées.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pipeline.sources.circuit_breaker import SourceUnavailableError
from pipeline.sources.datacite import harvest
from pipeline.sources.datacite.harvest import DataciteExtractor, DatacitePage, build_query
from pipeline.sources.harvest import ExtractionConfigError
from tests.helpers.extractors import arguments_du_run, extracteur


def test_requete_par_annee_et_mots_cles():
    assert build_query(2024, ["Clermont", "Univ. Clermont Auvergne"]) == (
        'publicationYear:2024 AND (creators.affiliation.name:"Clermont" '
        'OR creators.affiliation.name:"Univ. Clermont Auvergne")'
    )


def test_guillemets_d_un_mot_cle_echappes():
    assert build_query(2024, ['Labo "X"']) == (
        'publicationYear:2024 AND (creators.affiliation.name:"Labo \\"X\\"")'
    )


def _client(pages: list) -> MagicMock:
    client = MagicMock()
    client.count.return_value = sum(len(p.records) for p in pages if isinstance(p, DatacitePage))
    client.fetch_page.side_effect = pages
    return client


def test_suit_le_curseur_jusqu_a_la_derniere_page(configuration, ecritures):
    configuration(harvest)
    client = _client(
        [
            DatacitePage(records=[{"id": "10.1/a"}, {"id": "10.1/b"}], next_url="https://next/1"),
            DatacitePage(records=[{"id": "10.1/c"}], next_url=None),
        ]
    )
    assert extracteur(DataciteExtractor, client).run(arguments_du_run()).new == 3
    assert [c.args[2] for c in client.fetch_page.call_args_list] == [None, "https://next/1"]


def test_noeud_sans_doi_ignore(configuration, ecritures):
    configuration(harvest)
    client = _client([DatacitePage(records=[{"id": ""}, {"id": "10.1/b"}], next_url=None)])
    extracteur(DataciteExtractor, client).run(arguments_du_run())
    assert [e.source_id for e in ecritures] == ["10.1/b"]


def test_une_erreur_garde_les_pages_deja_ecrites(configuration, ecritures):
    configuration(harvest)
    client = _client(
        [
            DatacitePage(records=[{"id": "10.1/a"}], next_url="https://next/1"),
            RuntimeError("API indisponible"),
        ]
    )
    assert extracteur(DataciteExtractor, client).run(arguments_du_run()).new == 1


def test_source_indisponible_saute_les_annees_suivantes(configuration, ecritures):
    configuration(harvest, annees=[2023, 2024])
    client = _client([SourceUnavailableError("datacite")])
    metrics = extracteur(DataciteExtractor, client).run(arguments_du_run())
    assert metrics.total == 0
    assert client.fetch_page.call_count == 1


def test_configuration_sans_mot_cle_refusee(configuration):
    configuration(harvest, api_ids=[])
    with pytest.raises(ExtractionConfigError, match="aucun mot-clé"):
        extracteur(DataciteExtractor, _client([])).run(arguments_du_run())
