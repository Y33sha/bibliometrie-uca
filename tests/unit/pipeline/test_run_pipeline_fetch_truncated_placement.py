"""`fetch_truncated` est une phase distincte, entre `fetch_stale` et `normalize` ; les phases `harvest` et `normalize` l'excluent.

Elle recharge les enregistrements OpenAlex en staging, non traités, dont la liste d'auteurs est tronquée à 100, juste avant leur normalisation. Elle couvre donc aussi ceux qu'apportent `fetch_missing` et `fetch_stale`.
"""

from unittest.mock import AsyncMock, patch

from pipeline.ingestion.common import harvest, normalize
from pipeline.ingestion.common.normalizer import NormalizeStats
from pipeline.ingestion.openalex import fetch_truncated
from pipeline.runtime.context import RunOptions
from pipeline.runtime.execution import phase_context
from pipeline.runtime.observability.metrics import PhaseMetrics

# Tâche de la phase `fetch_truncated`, lancée par `asyncio.run`.
_REFETCH = "pipeline.ingestion.openalex.fetch_truncated.refetch_openalex"


def test_refetch_not_called_in_extract():
    with (
        patch.object(harvest, "_extraction_structure_count", return_value=1),
        patch.object(harvest, "run_harvest", return_value=PhaseMetrics()),
        patch(_REFETCH, new_callable=AsyncMock) as refetch,
    ):
        harvest.build().run(
            phase_context(
                RunOptions(mode="full"),
                credentials_missing=lambda _source: None,
                request_budget=lambda _source: None,
            )
        )
    assert refetch.call_count == 0


def test_refetch_not_called_in_normalize():
    with (
        patch.object(normalize, "_run_normalize", return_value=NormalizeStats(0, 0, 0)),
        patch("pipeline.runtime.execution.maintain"),
        patch.object(normalize, "_run_prune_disappeared", return_value=0),
        patch.object(normalize, "_run_cleanup_orphan_contributor_information", return_value=0),
        patch.object(normalize, "_run_cleanup_orphan_addresses", return_value=0),
        patch(_REFETCH, new_callable=AsyncMock) as refetch,
    ):
        normalize.build().run(
            phase_context(
                RunOptions(mode="full", sources={"openalex", "hal"}),
                credentials_missing=lambda _source: None,
                request_budget=lambda _source: None,
            )
        )
    assert refetch.call_count == 0


def test_refetch_called_in_own_phase_when_openalex_present():
    with (
        patch("pipeline.runtime.execution.get_sync_engine"),
        patch(_REFETCH, new_callable=AsyncMock, return_value=PhaseMetrics()) as refetch,
    ):
        fetch_truncated.build().run(
            phase_context(
                RunOptions(mode="full", sources={"openalex", "hal"}),
                credentials_missing=lambda _source: None,
                request_budget=lambda _source: None,
            )
        )
    assert refetch.call_count == 1


def test_refetch_skipped_in_own_phase_without_openalex():
    with patch(_REFETCH, new_callable=AsyncMock) as refetch:
        fetch_truncated.build().run(
            phase_context(
                RunOptions(mode="full", sources={"hal", "scanr"}),
                credentials_missing=lambda _source: None,
                request_budget=lambda _source: None,
            )
        )
    assert refetch.call_count == 0
