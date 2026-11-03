"""Exécuteur des tâches d'une phase (`pipeline.task_runner`)."""

import pytest

from pipeline.graph import Phase, task
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import TaskStep, execute_tasks, run_phase, run_tasks


def test_des_etapes_qui_ne_couvrent_pas_les_taches_de_la_phase_sont_refusees(contexte):
    steps = {"relations.inconnu": TaskStep(lambda _ctx: PhaseMetrics())}
    with pytest.raises(ValueError, match="divergent"):
        run_tasks("relations", steps, contexte())


def test_l_executeur_mesure_la_duree_des_seules_taches_executees(contexte):
    """Une tâche exécutée reçoit sa durée, rangée aussi dans le contexte. Une tâche écartée par sa condition est absente du résultat."""
    tasks = (
        task("essai.une", run=lambda _ctx: PhaseMetrics()),
        task("essai.ecartee", run=lambda _ctx: PhaseMetrics(), when=lambda _ctx: False),
        task("essai.deux", run=lambda _ctx: PhaseMetrics()),
    )

    ctx = contexte()
    by_task = execute_tasks(tasks, ctx)

    assert by_task["essai.une"].duration_s is not None
    assert "essai.ecartee" not in by_task
    assert set(ctx.task_durations) == {"essai.une", "essai.deux"}


_TACHES = (
    task("essai.une", run=lambda _ctx: PhaseMetrics(new=1)),
    task("essai.deux", run=lambda _ctx: PhaseMetrics(new=2)),
)


def test_une_phase_somme_par_defaut_les_metriques_de_ses_taches(contexte):
    assert run_phase(Phase("essai", "Essai", _TACHES), contexte()).new == 3


def test_une_phase_assemble_ses_metriques_par_sa_fonction(contexte):
    phase = Phase("essai", "Essai", _TACHES, assemble=lambda by_task: by_task["essai.deux"])

    assert run_phase(phase, contexte()).new == 2


def test_une_precondition_non_remplie_arrete_la_phase_avant_ses_taches(contexte):
    appels: list[str] = []

    def check(_ctx) -> None:
        raise RuntimeError("périmètre vide")

    tache = task("essai.une", run=lambda _ctx: appels.append("une") or PhaseMetrics())
    with pytest.raises(RuntimeError, match="périmètre vide"):
        run_phase(Phase("essai", "Essai", (tache,), check=check), contexte())

    assert appels == []
