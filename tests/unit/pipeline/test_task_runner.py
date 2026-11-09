"""Exécuteur des tâches d'une phase (`pipeline.task_runner`)."""

import logging

import pytest

from pipeline.graph import Phase, Step, Task
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import execute_tasks, run_phase


def test_l_executeur_mesure_la_duree_des_seules_taches_executees(contexte):
    """Une tâche exécutée reçoit sa durée, rangée aussi dans le contexte. Une tâche écartée par sa condition est absente du résultat."""
    tasks = (
        Task("une", run=lambda _ctx: PhaseMetrics()),
        Task("ecartee", run=lambda _ctx: PhaseMetrics(), when=lambda _ctx: False),
        Task("deux", run=lambda _ctx: PhaseMetrics()),
    )

    ctx = contexte()
    by_task = execute_tasks(tasks, ctx)

    assert by_task["une"].duration_s is not None
    assert "ecartee" not in by_task
    assert set(ctx.task_durations) == {"une", "deux"}


def test_l_executeur_ecrit_le_bilan_de_chaque_section_dans_l_ordre_des_taches(contexte, caplog):
    """Un groupe parallèle écrit ses lignes dans l'ordre des tâches. La dernière ligne d'une section la ferme. Une section aux tâches toutes silencieuses se ferme sur « Rien à faire »."""
    tasks = (
        Task(
            "issn",
            run=lambda _ctx: PhaseMetrics(report="a"),
            section="Revues",
            label="ISSN",
            parallel_group="g",
        ),
        Task(
            "titres",
            run=lambda _ctx: PhaseMetrics(report="b"),
            section="Revues",
            label="Titres",
            parallel_group="g",
        ),
        Task("types", run=lambda _ctx: PhaseMetrics(report="c"), section="Revues", label="Types"),
        Task(
            "editeurs",
            run=lambda _ctx: PhaseMetrics(),
            section="Éditeurs",
            label="Éditeurs",
            silent_when_empty=True,
        ),
    )

    with caplog.at_level(logging.INFO, logger="test"):
        execute_tasks(tasks, contexte())

    assert [record.getMessage() for record in caplog.records] == [
        "",
        "▶ Revues",
        "  ├─ ISSN : a",
        "  ├─ Titres : b",
        "  └─ Types : c",
        "",
        "▶ Éditeurs",
        "  └─ Rien à faire",
    ]


def test_une_etape_de_premier_niveau_donne_le_titre_de_section_de_ses_taches(contexte, caplog):
    """Les tâches d'une étape placée dans une autre écrivent sous le titre de l'étape englobante. Une tâche hors étape garde sa `section`."""

    def tache(name: str, **kwargs) -> Task:
        return Task(name, run=lambda _ctx: PhaseMetrics(report=name), label=name, **kwargs)

    children = (
        Step(
            "revues",
            "Revues",
            "ISSN → revues",
            (
                Step("issn", "ISSN", "ISSN → ISSN-L", (tache("sync"), tache("sudoc"))),
                tache("attach"),
            ),
        ),
        tache("editeurs", section="Éditeurs"),
    )

    with caplog.at_level(logging.INFO, logger="test"):
        execute_tasks(children, contexte())

    assert [record.getMessage() for record in caplog.records] == [
        "",
        "▶ Revues",
        "  ├─ sync : sync",
        "  ├─ sudoc : sudoc",
        "  └─ attach : attach",
        "",
        "▶ Éditeurs",
        "  └─ editeurs : editeurs",
    ]


_TACHES = (
    Task("une", run=lambda _ctx: PhaseMetrics(new=1)),
    Task("deux", run=lambda _ctx: PhaseMetrics(new=2)),
)


def test_une_phase_somme_par_defaut_les_metriques_de_ses_taches(contexte):
    assert run_phase(Phase("essai", "Essai", _TACHES), contexte()).new == 3


def test_une_phase_assemble_ses_metriques_par_sa_fonction(contexte):
    phase = Phase("essai", "Essai", _TACHES, assemble=lambda by_task: by_task["deux"])

    assert run_phase(phase, contexte()).new == 2


def test_une_precondition_non_remplie_arrete_la_phase_avant_ses_taches(contexte):
    appels: list[str] = []

    def check(_ctx) -> None:
        raise RuntimeError("périmètre vide")

    tache = Task("une", run=lambda _ctx: appels.append("une") or PhaseMetrics())
    with pytest.raises(RuntimeError, match="périmètre vide"):
        run_phase(Phase("essai", "Essai", (tache,), check=check), contexte())

    assert appels == []
