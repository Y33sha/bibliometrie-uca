"""Moissonnage ScanR brevets (`pipeline.ingestion.scanr_patents.harvest`).

Requête Elasticsearch : fonction pure. Pilotage : années de la configuration, identifiants de déposant, refus d'une configuration incomplète. Un faux client sert des pages scriptées, la configuration et l'écriture dans `staging` sont remplacées.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pipeline.ingestion.common.harvester import HarvestConfigError
from pipeline.ingestion.scanr_patents.harvest import (
    EXCLUDED_FIELDS,
    ScanrPatentsHarvester,
    build_query,
)
from tests.helpers.harvesters import arguments_du_run, moissonneur


def test_requete_par_annee_de_premier_depot_et_identifiant_de_deposant():
    q = build_query(2024, ["K4lR3", "S8ntZ"])
    assert q["query"]["bool"]["filter"] == [
        {"term": {"year": 2024}},
        {"terms": {"applicants.ids.id.keyword": ["K4lR3", "S8ntZ"]}},
    ]
    assert q["_source"] == {"excludes": list(EXCLUDED_FIELDS)}


def _client(pages: list[dict]) -> MagicMock:
    client = MagicMock()
    client.fetch_page.side_effect = pages
    client.count.return_value = sum(len(p["hits"]["hits"]) for p in pages)
    return client


def _page(*ids: str) -> dict:
    return {"hits": {"hits": [{"_source": {"id": i}, "sort": [i]} for i in ids]}}


def test_run_parcourt_les_annees_avec_les_identifiants_du_perimetre(configuration, ecritures):
    configuration(api_ids=["K4lR3"], annees=[2023, 2024])
    client = _client([_page("a"), _page(), _page("b"), _page()])
    assert moissonneur(ScanrPatentsHarvester, client).run(arguments_du_run()).new == 2
    assert [e.source for e in ecritures] == ["scanr_patents", "scanr_patents"]
    filtres = [appel.args[0]["query"]["bool"]["filter"] for appel in client.count.call_args_list]
    assert [f[0]["term"]["year"] for f in filtres] == [2023, 2024]
    assert filtres[0][1] == {"terms": {"applicants.ids.id.keyword": ["K4lR3"]}}


def test_run_sans_identifiant_de_deposant_refuse(configuration):
    configuration(api_ids=[])
    with pytest.raises(HarvestConfigError, match="aucun identifiant Paysage"):
        moissonneur(ScanrPatentsHarvester, _client([])).run(arguments_du_run())
