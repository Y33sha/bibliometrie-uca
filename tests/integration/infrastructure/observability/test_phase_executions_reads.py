"""Tests d'intégration : `last_daily_extract_date`, borne « depuis » du mode quotidien.

`last_daily_extract_date` prend le maximum sur toute la table, et `pipeline_phase_executions` contient des lignes committées par d'autres tests de la session. Les cas se placent donc en 2099, après toute ligne réelle.
"""

from __future__ import annotations

import datetime
from functools import partial

from infrastructure.observability.phase_executions import last_daily_extract_date
from tests.integration.helpers.pipeline_runs import insert_phase_execution

# Exécution quotidienne réussie de la source HAL par défaut.
_phase = partial(insert_phase_execution, mode="daily", status="ok", sources=["hal"])


def _at(day: int) -> datetime.datetime:
    return datetime.datetime(2099, 6, day, 8, 0, tzinfo=datetime.UTC)


class TestLastDailyHarvestDate:
    def test_jour_de_la_derniere_extraction_quotidienne(self, sa_sync_conn):
        _phase(sa_sync_conn, 1, phase="harvest", started_at=_at(10))
        _phase(sa_sync_conn, 2, phase="harvest", started_at=_at(15))
        assert last_daily_extract_date(sa_sync_conn) == datetime.date(2099, 6, 15)

    def test_extraction_par_annees_ignoree(self, sa_sync_conn):
        """Un moissonnage hors mode quotidien est ignoré : borné par années, il omet les dépôts récents."""
        _phase(sa_sync_conn, 1, phase="harvest", started_at=_at(10))
        _phase(sa_sync_conn, 2, phase="harvest", started_at=_at(20), mode="full")
        assert last_daily_extract_date(sa_sync_conn) == datetime.date(2099, 6, 10)

    def test_run_sans_extraction_ignore(self, sa_sync_conn):
        _phase(sa_sync_conn, 1, phase="harvest", started_at=_at(10))
        _phase(sa_sync_conn, 2, phase="publications", started_at=_at(20))
        assert last_daily_extract_date(sa_sync_conn) == datetime.date(2099, 6, 10)

    def test_extraction_avec_signal_ignoree(self, sa_sync_conn):
        """Un moissonnage en avertissement ou en erreur est ignoré (HAL indisponible, run interrompu) : les enregistrements sources non récupérés restent dans la fenêtre suivante."""
        _phase(sa_sync_conn, 1, phase="harvest", started_at=_at(10))
        _phase(sa_sync_conn, 2, phase="harvest", started_at=_at(20), status="warning")
        _phase(sa_sync_conn, 3, phase="harvest", started_at=_at(25), status="error")
        assert last_daily_extract_date(sa_sync_conn) == datetime.date(2099, 6, 10)
