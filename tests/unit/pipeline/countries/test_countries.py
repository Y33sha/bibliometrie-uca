"""Étape des pays de la phase `affiliations` : enchaînement des tâches et entonnoir.

L'étape relève deux bilans, avant la détection et après le choix du pays, et en tire un entonnoir : adresses sans pays au départ, adresses dotées d'un pays par la passe, adresses restantes. Les tâches ont leurs propres tests.
"""

import dataclasses
from unittest.mock import patch

import pytest

from pipeline.graph import in_transaction
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import execute_tasks
from pipeline.transformation.countries import countries as step
from pipeline.transformation.countries.countries import AddressCountryStatus

_PLACE_NAMES = in_transaction(lambda conn, logger: PhaseMetrics(new=6))
"""Détection par nom de lieu remplacée, dans sa transaction."""


class _FakeCountryQueries:
    """Faux accès SQL renvoyant les bilans successifs donnés à la construction : l'initial, puis le final."""

    def __init__(self, bilans: list[AddressCountryStatus]) -> None:
        self._bilans = list(bilans)

    def count_address_country_status(self, conn) -> AddressCountryStatus:
        return self._bilans.pop(0)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Simule les accès SQL de l'étape : bilans, résolution."""
        monkeypatch.setattr(step, "count_address_country_status", self.count_address_country_status)
        monkeypatch.setattr(step, "resolve_queued_addresses", lambda conn: 3)


def _run(contexte) -> dict[str, PhaseMetrics]:
    tasks = tuple(
        dataclasses.replace(t, run=_PLACE_NAMES) if t.name == "detect_by_place_name" else t
        for t in step.STEP.tasks
    )
    return execute_tasks(tasks, contexte(mode="daily"))


def _bilan(total: int, with_country: int) -> AddressCountryStatus:
    return AddressCountryStatus(total=total, with_country=with_country)


@pytest.fixture
def sous_etapes():
    """Neutralise les tâches et retient l'appel du recalcul."""
    appels: dict[str, object] = {}
    with (
        patch.object(step.detect_by_country_name, "run", return_value=PhaseMetrics(new=4)),
        patch.object(
            step.refresh_source_record_countries,
            "refresh",
            side_effect=lambda conn, log: appels.__setitem__("refresh", True),
        ),
    ):
        yield appels


def test_resume_l_entonnoir_des_bilans(contexte, sous_etapes, monkeypatch):
    _FakeCountryQueries([_bilan(100, 60), _bilan(100, 85)]).install(monkeypatch)

    by_task = _run(contexte)

    assert step.funnel(by_task) == {
        "cited_addresses": 100,
        "without_country_initial": 40,
        "without_country_pct": 40.0,
        "country_newly_attached": 25,
        "without_country_remaining": 15,
    }
    assert sous_etapes["refresh"] is True


def test_base_vide_sans_division_par_zero(contexte, sous_etapes, monkeypatch):
    _FakeCountryQueries([_bilan(0, 0), _bilan(0, 0)]).install(monkeypatch)

    assert step.funnel(_run(contexte))["without_country_pct"] == 0


def test_chaque_tache_dans_sa_transaction(open_tx, contexte, sous_etapes, monkeypatch):
    _FakeCountryQueries([_bilan(10, 5), _bilan(10, 9)]).install(monkeypatch)

    _run(contexte)

    assert open_tx.transactions == 4
