"""Phase `structure_referentials` : référentiels ROR et HAL, et leurs détails dans les métriques de la phase."""

from pipeline.phases import PHASES
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import run_phase
from tests.helpers.phase_tree import with_runs


def test_reprend_les_details_des_deux_referentiels(contexte):
    ror = PhaseMetrics()
    ror.details["ror"] = {"version": "v2.14", "imported": True}
    hal = PhaseMetrics()
    hal.details["hal_structures"] = {"loaded": 3}
    remplacees = {"refresh_ror": lambda _ctx: ror, "refresh_hal_structures": lambda _ctx: hal}
    referentials = next(p for p in PHASES if p.name == "structure_referentials")
    phase = with_runs(referentials, remplacees)

    metrics = run_phase(phase, contexte())

    assert metrics.details["ror"] == {"version": "v2.14", "imported": True}
    assert metrics.details["hal_structures"] == {"loaded": 3}
