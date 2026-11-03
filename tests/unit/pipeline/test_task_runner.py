"""Exécuteur des tâches d'une phase (`pipeline.task_runner`)."""

import pytest

from pipeline.graph import Phase, task
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import TaskStep, run_phase, run_tasks


def test_des_etapes_qui_ne_couvrent_pas_les_taches_de_la_phase_sont_refusees(contexte):
    steps = {"relations.inconnu": TaskStep(lambda _ctx: PhaseMetrics())}
    with pytest.raises(ValueError, match="divergent"):
        run_tasks("relations", steps, contexte())


def test_l_executeur_mesure_la_duree_des_seules_taches_executees(contexte):
    """Une tâche exécutée reçoit sa durée, rangée aussi dans le contexte. Une tâche écartée par sa condition garde `duration_s` à `None`."""
    steps = {
        "countries.detect": TaskStep(lambda _ctx: PhaseMetrics()),
        "countries.resolve": TaskStep(lambda _ctx: PhaseMetrics(), when=lambda _ctx: False),
        "countries.refresh_publication_countries": TaskStep(lambda _ctx: PhaseMetrics()),
    }

    ctx = contexte()
    by_task = run_tasks("countries", steps, ctx)

    assert by_task["countries.detect"].duration_s is not None
    assert by_task["countries.resolve"].duration_s is None
    assert set(ctx.task_durations) == {
        "countries.detect",
        "countries.refresh_publication_countries",
    }


_TACHES = (
    task("essai.une", run=lambda _ctx: PhaseMetrics(new=1)),
    task("essai.deux", run=lambda _ctx: PhaseMetrics(new=2)),
)


def test_une_phase_somme_par_defaut_les_metriques_de_ses_taches(contexte):
    assert run_phase(Phase("essai", "Essai", _TACHES), contexte()).new == 3


def test_une_phase_assemble_ses_metriques_par_sa_fonction(contexte):
    phase = Phase("essai", "Essai", _TACHES, assemble=lambda by_task: by_task["essai.deux"])

    assert run_phase(phase, contexte()).new == 2
