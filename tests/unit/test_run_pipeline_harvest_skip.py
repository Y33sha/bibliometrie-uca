"""Skip propre des sources d'extraction non configurées (phase `harvest`).

Une source dont la config d'extraction manque (`HarvestConfigError`) est
sautée avec un signal `source_unconfigured` (warning), sans interrompre le run :
les sources configurées aboutissent et sont seules listées dans la table par
source. Vaut pour la branche parallèle (full/weekly) et la branche HAL
incrémentale (daily).
"""

from unittest.mock import patch

from pipeline.ingestion.common import harvest
from pipeline.ingestion.common.harvester import HarvestConfigError
from pipeline.runtime.context import RunOptions
from pipeline.runtime.execution import phase_context
from pipeline.runtime.observability.metrics import PhaseMetrics


def _table_keys(metrics: PhaseMetrics) -> set[str]:
    rows = metrics.details.get("table", {}).get("rows", [])
    return {row["key"] for row in rows}


def test_phase_extract_full_skips_unconfigured_source():
    def _extract(_ctx, source, _make, _args):
        if source == "openalex":
            raise HarvestConfigError("ni clé ni email")
        return PhaseMetrics(new=7)

    with (
        patch.object(harvest, "_extraction_structure_count", return_value=1),
        patch.object(harvest, "run_harvest", side_effect=_extract),
    ):
        metrics = harvest.build().run(
            phase_context(
                RunOptions(mode="full", sources={"openalex", "theses"}),
                credentials_missing=lambda _source: None,
                request_budget=lambda _source: None,
            )
        )

    assert _table_keys(metrics) == {"theses"}
    assert metrics.new == 7
    assert any(s["code"] == "source_unconfigured" for s in metrics.signals)


def test_phase_extract_daily_hal_unconfigured():
    def _extract(_ctx, _source, _make, _args):
        raise HarvestConfigError("aucune collection")

    with (
        patch(
            "infrastructure.observability.phase_executions.get_last_daily_harvest_date",
            return_value=None,
        ),
        patch.object(harvest, "_extraction_structure_count", return_value=1),
        patch.object(harvest, "run_harvest", side_effect=_extract),
    ):
        metrics = harvest.build().run(
            phase_context(
                RunOptions(mode="daily"),
                credentials_missing=lambda _source: None,
                request_budget=lambda _source: None,
            )
        )

    assert _table_keys(metrics) == set()
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]
