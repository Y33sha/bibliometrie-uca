"""Moissonnage d'INSPIRE-HEP (`pipeline.ingestion.inspire.harvest`, `api`).

Requêtes : fonctions pures. Pilotage : années de la configuration, institutions du périmètre, refus d'une configuration incomplète. Un faux client sert des pages scriptées, la configuration et l'écriture dans `staging` sont remplacées.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pipeline.ingestion.common.harvester import HarvestConfigError
from pipeline.ingestion.common.pages import Page
from pipeline.ingestion.inspire import api
from pipeline.ingestion.inspire.harvest import InspireHarvester, affiliation_clause, build_query
from tests.helpers.harvesters import arguments_du_run, moissonneur


class TestRequetes:
    def test_numero_d_institution_et_nom_d_affiliation(self):
        assert affiliation_clause(["902740", ' LPC, "Clermont" ', ""]) == (
            'affid:902740 or aff:"LPC, \\"Clermont\\""'
        )

    def test_premiere_annee_de_la_fenetre(self):
        assert build_query(2017, ["902740", "2093671"], 2017) == (
            "(affid:902740 or affid:2093671) and date 2017"
        )

    def test_annee_suivante_sans_les_fiches_des_annees_precedentes(self):
        """Une fiche prépubliée en 2023 et publiée en 2024 revient seulement en 2023."""
        assert build_query(2024, ["902740"], 2017) == (
            "(affid:902740) and date 2024 and not date 2017->2023"
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
        assert requetes == [
            "(affid:902740) and date 2023",
            "(affid:902740) and date 2024 and not date 2023->2023",
        ]
        assert client.fetch_page.call_args_list[1].args[1] == (
            "https://inspirehep.net/api/literature/?page=2"
        )

    def test_sans_institution_refuse(self, configuration):
        configuration(api_ids=[])
        with pytest.raises(HarvestConfigError, match="aucune institution"):
            moissonneur(InspireHarvester, _client([])).run(arguments_du_run())


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
