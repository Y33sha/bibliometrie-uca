"""Moissonnage Web of Science (`pipeline.ingestion.wos.harvest`).

Pas de réseau ni de base : un faux client sert des réponses scriptées, la configuration et l'écriture dans `staging` sont remplacées, et la fixture `pauses` intercepte `time.sleep`.

Les tests vérifient le pilotage : pagination sur `firstRecord`, abandon après trois pages vides consécutives, plafond de l'API, isolement de l'échec d'une année, refus d'une configuration incomplète, arrêt sur circuit-breaker.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from pipeline.http.circuit_breaker import SourceUnavailableError
from pipeline.ingestion.common.harvester import HarvestConfigError
from pipeline.ingestion.common.staging import UpsertOutcome
from pipeline.ingestion.wos import harvest
from pipeline.ingestion.wos.harvest import WosHarvester, harvest_year
from pipeline.runtime.observability.progress import Progress
from tests.helpers.harvesters import arguments_du_run, moissonneur

_LOGGER = logging.getLogger("test")


@pytest.fixture(autouse=True)
def pauses(monkeypatch) -> list[float]:
    """Les pauses de ménagement de l'API sont relevées sans être faites."""
    relevees: list[float] = []
    monkeypatch.setattr(harvest.time, "sleep", relevees.append)
    return relevees


def _reponse(records: list[dict], *, total: int) -> dict:
    """Réponse de l'API : les records de la page, et le nombre de records trouvés."""
    return {
        "QueryResult": {"RecordsFound": total},
        "Data": {"Records": {"records": {"REC": records}}},
    }


def _records(*uids: str, route: UpsertOutcome = UpsertOutcome.NEW) -> list[dict]:
    return [{"UID": uid, "_route": route} for uid in uids]


def _client(reponses: list, *, total: int | None = None) -> MagicMock:
    client = MagicMock()
    client.fetch_page.side_effect = reponses
    client.count.return_value = total if total is not None else 0
    client.check_quota.return_value = "1000"
    return client


def _extraire(client: MagicMock):
    return harvest_year(client, MagicMock(), 2024, ["UCA"], _LOGGER, Progress(None, "WoS", None))


def test_pagination_sur_le_premier_record(ecritures):
    client = _client([_reponse(_records("W1", "W2"), total=3), _reponse(_records("W3"), total=3)])
    assert _extraire(client).new == 3
    assert [appel.args[1] for appel in client.fetch_page.call_args_list] == [1, 3]
    assert [e.source_id for e in ecritures] == ["W1", "W2", "W3"]


def test_ventilation_par_issue_de_l_ecriture(ecritures):
    records = _records("W1") + _records("W2", route=UpsertOutcome.UPDATED)
    metrics = _extraire(_client([_reponse(records, total=2)]))
    assert (metrics.new, metrics.updated) == (1, 1)


def test_requete_impossible(ecritures):
    assert _extraire(_client([None])).total == 0


def test_aucun_record_trouve(ecritures):
    assert _extraire(_client([_reponse([], total=0)])).total == 0
    assert ecritures == []


def test_trois_pages_vides_consecutives_arretent_l_annee(ecritures):
    client = _client([_reponse([], total=10)] * 3)
    assert _extraire(client).total == 0
    assert client.fetch_page.call_count == 3


def test_une_page_vide_isolee_est_retentee(ecritures):
    client = _client([_reponse([], total=2), _reponse(_records("W1", "W2"), total=2)])
    assert _extraire(client).new == 2


def test_plafond_de_l_api_interrompt(ecritures):
    """L'API refuse un `firstRecord` au-delà de cent mille : la boucle s'arrête là."""
    records = _records(*(f"W{i}" for i in range(100_001)))
    client = _client([_reponse(records, total=200_000)])
    assert _extraire(client).new == 100_001
    assert client.fetch_page.call_count == 1


def test_run_parcourt_les_annees_de_la_configuration(configuration, ecritures):
    configuration(harvest, annees=[2023, 2024])
    client = _client([_reponse(_records("W1"), total=1), _reponse(_records("W2"), total=1)])
    assert moissonneur(WosHarvester, client).run(arguments_du_run()).new == 2


def test_run_isole_l_echec_d_une_annee(configuration, ecritures):
    """Une année qui lève laisse la suivante s'exécuter."""
    configuration(harvest, annees=[2023, 2024])
    client = _client([RuntimeError("API en panne"), _reponse(_records("W1"), total=1)])
    assert moissonneur(WosHarvester, client).run(arguments_du_run()).new == 1


def test_run_survit_a_un_comptage_impossible(configuration, ecritures):
    """Un comptage qui lève compte l'année pour zéro : son extraction s'exécute quand même."""
    configuration(harvest)
    client = _client([_reponse(_records("W1"), total=1)])
    client.count.side_effect = RuntimeError("API en panne")
    assert moissonneur(WosHarvester, client).run(arguments_du_run()).new == 1


def test_run_survit_a_un_quota_illisible(configuration, ecritures):
    configuration(harvest)
    client = _client([_reponse([], total=0)])
    client.check_quota.side_effect = RuntimeError("service indisponible")
    assert moissonneur(WosHarvester, client).run(arguments_du_run()).total == 0


def test_run_sans_affiliation_refuse(configuration):
    configuration(harvest, api_ids=[])
    with pytest.raises(HarvestConfigError, match="aucune affiliation"):
        moissonneur(WosHarvester, _client([])).run(arguments_du_run())


def test_run_s_arrete_quand_la_source_devient_indisponible(configuration, ecritures, pauses):
    """Retries épuisés pendant une année : les années suivantes sont sautées sans pause, les métriques déjà acquises sont gardées."""
    configuration(harvest, annees=[2023, 2024, 2025])
    client = _client([_reponse(_records("W1"), total=1), SourceUnavailableError("wos")])
    metrics = moissonneur(WosHarvester, client).run(arguments_du_run())
    assert metrics.new == 1
    assert client.fetch_page.call_count == 2
    # Une seule pause, entre 2023 et 2024.
    assert pauses == [30]


def test_run_s_arrete_quand_le_comptage_trouve_la_source_indisponible(configuration):
    configuration(harvest, annees=[2023, 2024])
    client = _client([])
    client.count.side_effect = SourceUnavailableError("wos")
    with pytest.raises(SourceUnavailableError):
        moissonneur(WosHarvester, client).run(arguments_du_run())
    assert client.count.call_count == 1
    client.fetch_page.assert_not_called()
