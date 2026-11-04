"""Tests de l'enchaînement de la phase `publishing`, exécutée tâche par tâche dans l'ordre du graphe."""

import dataclasses

from pipeline.phases import PHASES
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import run_phase
from pipeline.transformation.publishing import publishing

_PHASE = next(phase for phase in PHASES if phase.name == "publishing")
_CHAMPS = tuple(task.name for task in publishing.TASKS)


def _run(
    contexte,
    appels: list[str] | None = None,
    *,
    credentials_missing: str | None = None,
    **metrics: PhaseMetrics,
) -> PhaseMetrics:
    """Exécute la phase avec ses tâches réelles, leurs fonctions remplacées par des enregistreurs."""
    appels = [] if appels is None else appels

    def runner(champ: str):
        def run(_ctx) -> PhaseMetrics:
            appels.append(champ)
            return metrics.get(champ, PhaseMetrics())

        return run

    tasks = tuple(dataclasses.replace(task, run=runner(task.name)) for task in _PHASE.tasks)
    return run_phase(
        dataclasses.replace(_PHASE, tasks=tasks),
        contexte(credentials_missing=lambda _source: credentials_missing),
    )


def test_la_table_d_observabilite_couvre_les_taches_de_la_phase():
    """Chaque tâche a sa ligne, dans l'ordre d'exécution, sauf l'import du DOAJ, compté à part dans le résumé."""
    assert list(publishing._IDENTIFIED) == [
        name for name in _CHAMPS if name != "enrich_serials_from_doaj"
    ]


def test_les_taches_s_enchainent_dans_l_ordre_du_graphe(contexte):
    appels: list[str] = []
    _run(contexte, appels)
    assert appels == list(_CHAMPS)


def test_les_compteurs_des_taches_remontent_a_la_phase(contexte):
    publishers = PhaseMetrics()
    publishers.add(new=1, publisher_matched=2)
    metrics = _run(
        contexte,
        resolve_crossref_publishers=publishers,
        check_serials_in_openalex=PhaseMetrics(updated=5),
    )
    assert (metrics.new, metrics.updated) == (1, 5)
    assert metrics.extras.get("publisher_matched") == 2


def test_les_signaux_des_taches_remontent_a_la_phase(contexte):
    publishers = PhaseMetrics()
    publishers.signals.append(
        {"level": "warning", "code": "source_unavailable", "message": "crossref : arrêt"}
    )
    metrics = _run(contexte, resolve_crossref_publishers=publishers)
    assert [s["code"] for s in metrics.signals] == ["source_unavailable"]


def test_acces_non_configure_saute_les_taches_a_source(contexte):
    """Sans identifiants, une tâche à source est sautée avant l'appel de sa fonction, et signalée."""
    appels: list[str] = []
    metrics = _run(contexte, appels, credentials_missing="clé absente")
    assert "check_serials_in_openalex" not in appels
    assert "attach_serials" in appels  # tâche sans source
    assert {s["code"] for s in metrics.signals} == {"source_unconfigured"}
