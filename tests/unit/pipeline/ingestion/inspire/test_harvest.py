"""Moissonnage d'INSPIRE-HEP (`pipeline.ingestion.inspire.harvest`, `person_search`, `api`).

Requêtes : fonctions pures. Pilotage : années de la configuration, institutions du périmètre, refus d'une configuration incomplète, fiches écrites une fois par run. Un faux client sert des pages scriptées, la configuration et l'écriture dans `staging` sont remplacées.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from domain.sources.staging import StagingEntryMode
from pipeline.ingestion.common.harvester import HarvestConfigError
from pipeline.ingestion.common.pages import Page
from pipeline.ingestion.inspire import api
from pipeline.ingestion.inspire.harvest import InspireHarvester, affiliation_clause, build_query
from pipeline.ingestion.inspire.person_search import InspirePersonHarvester, build_orcid_query
from tests.helpers.harvesters import arguments_du_run, moissonneur


class TestRequetes:
    def test_numero_d_institution_et_nom_d_affiliation(self):
        assert affiliation_clause(["902740", ' LPC, "Clermont" ', ""]) == (
            'affid:902740 or aff:"LPC, \\"Clermont\\""'
        )

    def test_annee(self):
        assert build_query(2024, ["902740", "2093671"]) == (
            "(affid:902740 or affid:2093671) and date 2024"
        )

    def test_orcid_et_plage_d_annees(self):
        assert build_orcid_query(["0000-0001-2345-6789", "0000-0002-0000-000X"], 2017, 2026) == (
            '(authors.ids.value:"0000-0001-2345-6789" or authors.ids.value:"0000-0002-0000-000X")'
            " and date 2017->2026"
        )


def _client(pages: list[Page]) -> MagicMock:
    client = MagicMock()
    client.fetch_page.side_effect = pages
    client.count.return_value = sum(len(p.records) for p in pages)
    return client


class TestMoissonnageParInstitution:
    def test_parcourt_les_annees_avec_les_institutions_du_perimetre(self, configuration, ecritures):
        configuration(api_ids=["902740"], annees=[2023, 2024])
        client = _client(
            [
                Page([{"control_number": 1}], "https://inspirehep.net/api/literature/?page=2"),
                Page([], None),
                Page([{"control_number": 2, "dois": [{"value": "10.1103/X"}]}], None),
            ]
        )
        assert moissonneur(InspireHarvester, client).run(arguments_du_run()).new == 2
        assert [(e.source, e.source_id, e.doi) for e in ecritures] == [
            ("inspire", "1", None),
            ("inspire", "2", "10.1103/x"),
        ]
        requetes = [appel.args[0] for appel in client.count.call_args_list]
        assert requetes == ["(affid:902740) and date 2023", "(affid:902740) and date 2024"]
        assert client.fetch_page.call_args_list[1].args[1] == (
            "https://inspirehep.net/api/literature/?page=2"
        )

    def test_sans_institution_refuse(self, configuration):
        configuration(api_ids=[])
        with pytest.raises(HarvestConfigError, match="aucune institution"):
            moissonneur(InspireHarvester, _client([])).run(arguments_du_run())


def test_fiche_ramenee_par_deux_lots_ecrite_une_fois(identifiants_rh, ecritures):
    lot = InspirePersonHarvester.BATCH_SIZE
    identifiants_rh([f"0000-0000-0000-{i:04d}" for i in range(lot + 1)])
    client = MagicMock()
    client.fetch_page.side_effect = [
        Page([{"control_number": 1}, {"control_number": 2}], None),
        Page([{"control_number": 1}, {}], None),
    ]

    metrics = moissonneur(InspirePersonHarvester, client).run(arguments_du_run())

    assert [e.source_id for e in ecritures] == ["1", "2"]
    assert {e.entry_mode for e in ecritures} == {StagingEntryMode.PERSON_IDENTIFIER}
    assert metrics.new == 2


def test_page_reduite_aux_metadonnees_des_fiches(monkeypatch):
    reponse = {
        "hits": {
            "hits": [{"created": "x", "updated": "y", "metadata": {"control_number": 7}}],
            "total": 1,
        },
        "links": {"next": "https://inspirehep.net/api/literature/?page=2"},
    }
    monkeypatch.setattr(api, "http_request_with_retry", lambda *args, **kwargs: reponse)

    page = api.InspireClient().fetch_page("affid:902740", None, "2024")

    assert page.records == [{"control_number": 7}]
    assert page.next_token == "https://inspirehep.net/api/literature/?page=2"
