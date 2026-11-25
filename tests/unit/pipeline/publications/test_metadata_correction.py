"""Orchestrateur de la phase de correction des métadonnées.

Quatre passes se succèdent. La correction unaire reclasse le type de document d'après le type de la revue. Le calcul des cibles des DOI précède le retrait des DOI, qui épargne le DOI d'une forme secondaire. Le calcul de `is_matchable` vient en dernier : il lit le DOI, les identifiants, les liens et les cibles corrigés par les passes précédentes.

La phase assemble ensuite un bilan : les compteurs des passes, et la ventilation par règle déclenchée, de la plus fréquente à la moins fréquente.
"""

from pipeline.phases import PHASES
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import run_phase
from tests.helpers.phase_tree import with_runs

_PHASE = next(p for p in PHASES if p.name == "metadata_correction")


def _run(contexte, **by_task: PhaseMetrics):
    """Exécute la phase, chaque tâche remplacée par l'enregistrement de son passage et ses métriques `by_task[nom]`."""
    ordre: list[str] = []

    def run(name):
        return lambda _ctx: ordre.append(name) or by_task.get(name, PhaseMetrics())

    phase = with_runs(_PHASE, {t.name: run(t.name) for t in _PHASE.tasks})
    return run_phase(phase, contexte()), ordre


def test_ordre_des_passes(contexte):
    """Les cibles précèdent les retraits ; `is_matchable` vient en dernier."""
    _, ordre = _run(contexte)

    assert ordre == [
        "correct_source_records",
        "doi_targets",
        "remove_identifiers",
        "decide_matchability",
    ]


def test_bilan_assemble_des_passes(contexte):
    metrics, _ = _run(
        contexte,
        correct_source_records=PhaseMetrics(seen=20, updated=6),
        doi_targets=PhaseMetrics(seen=5, updated=3),
        remove_identifiers=PhaseMetrics(seen=30, updated=1),
        decide_matchability=PhaseMetrics(seen=40, updated=2),
    )

    assert metrics.total == 95
    assert metrics.updated == 12
    assert metrics.details["summary"] == {
        "correct_source_records_examined": 20,
        "correct_source_records_corrected": 6,
        "doi_targets_examined": 5,
        "doi_targets_corrected": 3,
        "remove_identifiers_examined": 30,
        "remove_identifiers_corrected": 1,
        "decide_matchability_examined": 40,
        "decide_matchability_corrected": 2,
    }


def test_ventilation_des_regles_du_plus_frequent_au_moins(contexte):
    """Les déclenchements des passes correctrices se rejoignent dans un même classement."""
    metrics, _ = _run(
        contexte,
        correct_source_records=PhaseMetrics(extras={"type_absent": 2}),
        doi_targets=PhaseMetrics(extras={"version_vers_concept": 5}),
        remove_identifiers=PhaseMetrics(extras={"chapitre": 1}),
    )

    assert metrics.details["table"]["rows"] == [
        {"key": "version_vers_concept", "count": 5},
        {"key": "type_absent", "count": 2},
        {"key": "chapitre", "count": 1},
    ]
