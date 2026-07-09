"""Skip propre des sources d'extraction non configurées (`phase_extract`).

Une source dont la config d'extraction manque (`ExtractionConfigError`) est
sautée avec un signal `source_unconfigured` (warning), sans interrompre le run :
les sources configurées aboutissent et sont seules listées dans la table par
source. Vaut pour la branche parallèle (full/weekly) et la branche HAL
incrémentale (daily).
"""

from unittest.mock import patch

import run_pipeline
from application.pipeline.extract.base import ExtractionConfigError
from application.pipeline.metrics import PhaseMetrics


def _table_keys(metrics: PhaseMetrics) -> set[str]:
    rows = metrics.details.get("table", {}).get("rows", [])
    return {row["key"] for row in rows}


def test_parallel_extractors_skip_unconfigured():
    def _ok() -> PhaseMetrics:
        return PhaseMetrics(new=3)

    def _unconfigured() -> PhaseMetrics:
        raise ExtractionConfigError("aucune clé")

    metrics = PhaseMetrics()
    by_source = run_pipeline._run_parallel_extractors(
        [("openalex", _unconfigured), ("theses", _ok)], metrics
    )

    assert "openalex" not in by_source  # source sautée : aucune ligne
    assert by_source["theses"]["new"] == 3
    assert metrics.new == 3  # la source configurée est bien mergée
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]
    assert metrics.signals[0]["level"] == "warning"


def test_phase_extract_full_skips_unconfigured_source():
    def _extract(source, _make, _args):
        if source == "openalex":
            raise ExtractionConfigError("ni clé ni email")
        return PhaseMetrics(new=7)

    with patch.object(run_pipeline, "_run_extract", side_effect=_extract):
        metrics = run_pipeline.phase_extract(mode="full", sources={"openalex", "theses"})

    assert _table_keys(metrics) == {"theses"}
    assert metrics.new == 7
    assert any(s["code"] == "source_unconfigured" for s in metrics.signals)


def test_phase_extract_daily_hal_unconfigured():
    def _extract(_source, _make, _args):
        raise ExtractionConfigError("aucune collection")

    with (
        patch(
            "infrastructure.observability.phase_executions.get_last_extract_date",
            return_value=None,
        ),
        patch.object(run_pipeline, "_run_extract", side_effect=_extract),
    ):
        metrics = run_pipeline.phase_extract(mode="daily")

    assert _table_keys(metrics) == set()
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]
