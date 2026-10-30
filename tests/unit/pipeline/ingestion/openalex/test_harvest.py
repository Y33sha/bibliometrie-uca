"""Moissonnage OpenAlex (`pipeline.ingestion.openalex.harvest`).

Paramètres de requête : fonction pure. Pilotage : pagination par curseur jusqu'à son épuisement, marquage des works tronqués, mode incrémental, refus d'une configuration incomplète, arrêt sur circuit-breaker. Pas de réseau ni de base : un faux client sert des pages scriptées, la configuration et l'écriture dans `staging` sont remplacées.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from pipeline.ingestion.common.harvester import HarvestConfigError
from pipeline.ingestion.common.staging import UpsertOutcome
from pipeline.ingestion.openalex import api, harvest
from pipeline.ingestion.openalex.api import build_params
from pipeline.ingestion.openalex.harvest import OpenalexHarvester, harvest_period
from pipeline.runtime.observability.progress import Progress
from tests.helpers.harvesters import arguments_du_run, moissonneur

_LOGGER = logging.getLogger("test")


def _auth(monkeypatch, *, api_key=None, email=None):
    """Pose la clé d'API et l'adresse polite pool lues par `auth_params()`."""
    monkeypatch.setattr(api, "get_openalex_api_key", lambda: api_key)
    monkeypatch.setattr(api, "get_polite_pool_email_optional", lambda: email)


@pytest.fixture(autouse=True)
def _sans_auth(monkeypatch):
    _auth(monkeypatch)


class TestBuildParams:
    def test_year_filter(self):
        params = build_params(["I1"], years=[2024])
        assert params["filter"] == "authorships.institutions.lineage:I1,publication_year:2024"

    def test_years_range_uses_min_and_max(self):
        params = build_params(["I1"], years=[2023, 2026, 2024])
        assert params["filter"] == "authorships.institutions.lineage:I1,publication_year:2023-2026"

    def test_combines_years_and_since(self):
        params = build_params(["I1"], years=[2024, 2026], since="2026-05-01")
        assert params["filter"] == (
            "authorships.institutions.lineage:I1,publication_year:2024-2026,"
            "from_updated_date:2026-05-01"
        )

    def test_lineage_joins_multiple_institutions(self):
        params = build_params(["I1", "I2", "I3"], years=[2024])
        assert params["filter"] == (
            "authorships.institutions.lineage:I1|I2|I3,publication_year:2024"
        )

    def test_select_and_cursor(self):
        params = build_params(["I1"], years=[2024])
        assert params["select"]
        assert params["cursor"] == "*"
        assert build_params(["I1"], years=[2024], cursor="abc123")["cursor"] == "abc123"

    def test_auth_api_key_included(self, monkeypatch):
        _auth(monkeypatch, api_key="testkey", email="test@example.com")
        params = build_params(["I1"], years=[2024])
        assert params.get("api_key") == "testkey"
        assert "mailto" not in params

    def test_auth_email_fallback(self, monkeypatch):
        _auth(monkeypatch, email="test@example.com")
        params = build_params(["I1"], years=[2024])
        assert params.get("mailto") == "test@example.com"
        assert "api_key" not in params


def _avancement() -> Progress:
    return Progress(None, "OpenAlex", None)


def _work(identifiant: str, *, route: UpsertOutcome = UpsertOutcome.NEW, auteurs: int = 1) -> dict:
    return {
        "id": f"https://openalex.org/{identifiant}",
        "authorships": [{"author": {}}] * auteurs,
        "_route": route,
    }


def _page(works: list[dict], *, next_cursor: str | None = None, count: int | None = None) -> dict:
    meta: dict = {}
    if count is not None:
        meta["count"] = count
    if next_cursor is not None:
        meta["next_cursor"] = next_cursor
    return {"meta": meta, "results": works}


def _client(pages: list[dict]) -> MagicMock:
    client = MagicMock()
    client.fetch_page.side_effect = pages
    client.count.return_value = sum(len(p["results"]) for p in pages)
    return client


def _extraire(client: MagicMock, years: list[int] | None = None):
    return harvest_period(
        client, MagicMock(), ["I1"], _LOGGER, _avancement(), years=years or [2024]
    )


def test_pagination_jusqu_a_l_epuisement_du_curseur(ecritures):
    client = _client(
        [_page([_work("W1"), _work("W2")], next_cursor="c2", count=3), _page([_work("W3")])]
    )
    assert _extraire(client).new == 3
    assert [appel.kwargs["cursor"] for appel in client.fetch_page.call_args_list] == ["*", "c2"]
    assert [e.source_id for e in ecritures] == ["W1", "W2", "W3"]


def test_ventilation_par_issue_de_l_ecriture(ecritures):
    client = _client(
        [
            _page(
                [
                    _work("W1"),
                    _work("W2", route=UpsertOutcome.UPDATED),
                    _work("W3", route=UpsertOutcome.UNCHANGED),
                ]
            )
        ]
    )
    metrics = _extraire(client)
    assert (metrics.new, metrics.updated, metrics.unchanged) == (1, 1, 1)


def test_work_au_plafond_d_auteurs_marque_tronque(ecritures):
    client = _client([_page([_work("W1", auteurs=100), _work("W2", auteurs=3)])])
    _extraire(client)
    assert [e.authors_truncated for e in ecritures] == [True, False]


def test_page_sans_resultat_interrompt(ecritures):
    client = _client([_page([], next_cursor="c2", count=10)])
    assert _extraire(client).total == 0
    assert ecritures == []


def test_run_parcourt_les_annees_de_la_configuration(configuration, ecritures):
    configuration(harvest, annees=[2023, 2024])
    client = _client([_page([_work("W1")]), _page([_work("W2")])])
    metrics = moissonneur(OpenalexHarvester, client).run(arguments_du_run())
    assert metrics.new == 2
    assert [appel.kwargs["years"] for appel in client.count.call_args_list] == [[2023], [2024]]


def test_run_avec_une_annee_demandee_ignore_la_configuration(configuration, ecritures):
    configuration(harvest, annees=[2020, 2021])
    client = _client([_page([_work("W1")])])
    moissonneur(OpenalexHarvester, client).run(arguments_du_run(year=2024))
    assert client.fetch_page.call_args.kwargs["years"] == [2024]


def test_run_incremental_fait_une_seule_passe_sur_la_date(configuration, ecritures):
    configuration(harvest, annees=[2020, 2021, 2022])
    client = _client([_page([_work("W1")])])
    moissonneur(OpenalexHarvester, client).run(arguments_du_run(since="2026-01-01"))
    assert client.fetch_page.call_count == 1
    assert client.fetch_page.call_args.kwargs["since"] == "2026-01-01"
    assert client.count.call_args.kwargs["since"] == "2026-01-01"


def test_run_incremental_garde_les_annees_du_mode_complet(configuration, ecritures):
    configuration(harvest, annees=[2020, 2021, 2022])
    client = _client([_page([_work("W1")])])
    moissonneur(OpenalexHarvester, client).run(arguments_du_run(since="2026-01-01"))
    assert client.fetch_page.call_args.kwargs["years"] == [2020, 2021, 2022]
    assert client.count.call_args.kwargs["years"] == [2020, 2021, 2022]


def test_run_sans_institution_refuse(configuration):
    configuration(harvest, api_ids=[])
    with pytest.raises(HarvestConfigError, match="aucun institution_id"):
        moissonneur(OpenalexHarvester, _client([])).run(arguments_du_run())
