"""Moissonnage ScanR (`pipeline.ingestion.scanr.harvest`) et champs des documents.

Requête Elasticsearch et champs : fonctions pures. Pilotage : pagination `search_after` jusqu'à la page vide, refus d'une configuration incomplète, arrêt sur circuit-breaker. Pas de réseau ni de base : un faux client sert des pages scriptées, la configuration et l'écriture dans `staging` sont remplacées.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pipeline.ingestion.api_params import SCANR_PER_PAGE
from pipeline.ingestion.common.harvester import HarvestConfigError
from pipeline.ingestion.common.staging import UpsertOutcome
from pipeline.ingestion.scanr import harvest
from pipeline.ingestion.scanr.fields import extract_doi, extract_id
from pipeline.ingestion.scanr.harvest import ScanrHarvester, build_query, harvest_year
from pipeline.runtime.observability.progress import Progress
from tests.helpers.harvesters import arguments_du_run, moissonneur


class TestBuildQuery:
    def test_basic_shape(self):
        q = build_query(year=2024, affiliation_ids=["A1", "A2"])
        assert q["size"] == SCANR_PER_PAGE
        assert q["query"]["bool"]["filter"] == [
            {"term": {"year": 2024}},
            {"terms": {"affiliations.id.keyword": ["A1", "A2"]}},
        ]
        assert q["sort"] == [{"id.keyword": "asc"}]

    def test_search_after_only_when_provided(self):
        assert "search_after" not in build_query(year=2024, affiliation_ids=["A1"])
        q = build_query(year=2024, affiliation_ids=["A1"], search_after=["last-id-123"])
        assert q["search_after"] == ["last-id-123"]

    def test_track_total_only_when_requested(self):
        assert build_query(year=2024, affiliation_ids=["A1"])["track_total_hits"] is False
        q = build_query(year=2024, affiliation_ids=["A1"], track_total=True)
        assert q["track_total_hits"] is True


class TestFields:
    def test_extract_id(self):
        assert extract_id({"id": "doi10.1000/abc"}) == "doi10.1000/abc"
        assert extract_id({}) == ""

    def test_extract_doi_first_doi_of_external_ids(self):
        doc = {
            "externalIds": [
                {"type": "hal", "id": "hal-123"},
                {"type": "doi", "id": "https://doi.org/10.1000/first"},
                {"type": "doi", "id": "10.1000/second"},
            ]
        }
        assert extract_doi(doc) == "10.1000/first"

    def test_extract_doi_none(self):
        assert extract_doi({"externalIds": [{"type": "hal", "id": "hal-123"}]}) is None
        assert extract_doi({}) is None
        assert extract_doi({"externalIds": None}) is None


def _hit(identifiant: str, route: UpsertOutcome = UpsertOutcome.NEW) -> dict:
    """Document Elasticsearch minimal : la source, et la clé de tri qui sert de curseur."""
    return {"_source": {"id": identifiant, "_route": route}, "sort": [identifiant]}


def _page(hits: list[dict]) -> dict:
    return {"hits": {"hits": hits}}


def _client(pages: list[dict]) -> MagicMock:
    client = MagicMock()
    client.fetch_page.side_effect = pages
    client.count.return_value = sum(len(p["hits"]["hits"]) for p in pages)
    return client


def _extraire(client: MagicMock):
    return harvest_year(client, MagicMock(), 2024, ["S1"], Progress(None, "ScanR", None))


def test_pagination_jusqu_a_la_page_vide(ecritures):
    client = _client([_page([_hit("a"), _hit("b")]), _page([_hit("c")]), _page([])])
    assert _extraire(client).new == 3


def test_ventilation_par_issue_de_l_ecriture(ecritures):
    hits = [_hit("a"), _hit("b", UpsertOutcome.UPDATED), _hit("c", UpsertOutcome.UNCHANGED)]
    metrics = _extraire(_client([_page(hits), _page([])]))
    assert (metrics.new, metrics.updated, metrics.unchanged) == (1, 1, 1)


def test_document_sans_identifiant_ignore(ecritures):
    _extraire(_client([_page([_hit(""), _hit("b")]), _page([])]))
    assert [e.source_id for e in ecritures] == ["b"]


def test_le_curseur_suit_la_cle_de_tri_du_dernier_document(ecritures):
    client = _client([_page([_hit("a"), _hit("b")]), _page([])])
    _extraire(client)
    requetes = [appel.args[0] for appel in client.fetch_page.call_args_list]
    assert "search_after" not in requetes[0]
    assert requetes[1]["search_after"] == ["b"]


def test_run_parcourt_les_annees_de_la_configuration(configuration, ecritures):
    configuration(harvest, annees=[2023, 2024])
    client = _client([_page([_hit("a")]), _page([]), _page([_hit("b")]), _page([])])
    assert moissonneur(ScanrHarvester, client).run(arguments_du_run()).new == 2
    annees = [
        appel.args[0]["query"]["bool"]["filter"][0]["term"]["year"]
        for appel in client.count.call_args_list
    ]
    assert annees == [2023, 2024]


def test_run_avec_une_annee_demandee_ignore_la_configuration(configuration, ecritures):
    configuration(harvest, annees=[2020, 2021, 2022])
    client = _client([_page([_hit("a")]), _page([])])
    assert moissonneur(ScanrHarvester, client).run(arguments_du_run(year=2024)).total == 1
    filtre = client.fetch_page.call_args_list[0].args[0]["query"]["bool"]["filter"]
    assert filtre[0] == {"term": {"year": 2024}}


def test_run_sans_affiliation_refuse(configuration):
    configuration(harvest, api_ids=[])
    with pytest.raises(HarvestConfigError, match="aucun affiliation_id"):
        moissonneur(ScanrHarvester, _client([])).run(arguments_du_run())
