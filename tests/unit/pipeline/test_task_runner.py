"""Exécuteur des tâches d'une phase (`pipeline.task_runner`)."""

import pytest

from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import TaskStep, run_tasks


def test_des_etapes_qui_ne_couvrent_pas_les_taches_de_la_phase_sont_refusees(contexte):
    steps = {"relations.inconnu": TaskStep(lambda _ctx: PhaseMetrics())}
    with pytest.raises(ValueError, match="divergent"):
        run_tasks("relations", steps, contexte())


def test_l_executeur_mesure_la_duree_des_seules_taches_executees(contexte):
    """Une tâche exécutée reçoit sa durée. Une tâche écartée par sa condition garde `duration_s` à `None`."""
    steps = {
        "countries.detect": TaskStep(lambda _ctx: PhaseMetrics()),
        "countries.resolve": TaskStep(lambda _ctx: PhaseMetrics(), when=lambda _ctx: False),
        "countries.refresh_publication_countries": TaskStep(lambda _ctx: PhaseMetrics()),
    }

    by_task = run_tasks("countries", steps, contexte())

    assert by_task["countries.detect"].duration_s is not None
    assert by_task["countries.resolve"].duration_s is None
