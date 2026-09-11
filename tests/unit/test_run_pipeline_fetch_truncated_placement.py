"""Régression : `fetch_truncated` est une phase distincte, placée entre
`fetch_stale` et `normalize` (ni dans `phase_extract`, ni dans `phase_normalize`).

Elle cible les works OpenAlex staging à 100 auteurs `processed=FALSE` juste avant
que normalize ne les consomme — placement qui capte aussi les tronqués ramenés
par fetch_missing et fetch_stale. La placer en extract (état antérieur) les
ratait ; la garder dans normalize mêlait un fetch réseau à une phase de
transformation.
"""

from unittest.mock import AsyncMock, patch

from application.pipeline.metrics import PhaseMetrics
from interfaces.cli import run_pipeline

# L'orchestrateur applicatif du refetch, câblé par `phase_fetch_truncated` via `asyncio.run`.
_REFETCH = "application.pipeline.extract.fetch_truncated.refetch"


def test_refetch_not_called_in_extract():
    with (
        patch.object(run_pipeline, "_extraction_structure_count", return_value=1),
        patch.object(run_pipeline, "_run_extract", return_value=PhaseMetrics()),
        patch(_REFETCH, new_callable=AsyncMock) as refetch,
    ):
        run_pipeline.phase_extract(run_pipeline.RunOptions(mode="full"))
    assert refetch.call_count == 0


def test_refetch_not_called_in_normalize():
    # La ligne d'observabilité d'une source, dont la phase somme les documents normalisés.
    ligne = {"key": "openalex", "processed": 0, "skipped": 0, "errors": 0, "duration_s": 0.0}
    with (
        patch.object(run_pipeline, "_run_normalize", return_value=ligne),
        patch.object(run_pipeline, "_vacuum_staging"),
        patch.object(run_pipeline, "_run_prune_disappeared"),
        patch.object(run_pipeline, "_run_cleanup_orphan_identities"),
        patch(_REFETCH, new_callable=AsyncMock) as refetch,
    ):
        run_pipeline.phase_normalize(
            run_pipeline.RunOptions(mode="full", sources={"openalex", "hal"})
        )
    assert refetch.call_count == 0


def test_refetch_called_in_own_phase_when_openalex_present():
    with (
        patch("infrastructure.db.engine.get_sync_engine"),
        patch("infrastructure.sources.openalex.fetch_truncated.PgOpenalexFetchTruncatedAdapter"),
        patch(_REFETCH, new_callable=AsyncMock, return_value=PhaseMetrics()) as refetch,
    ):
        run_pipeline.phase_fetch_truncated(
            run_pipeline.RunOptions(mode="full", sources={"openalex", "hal"})
        )
    assert refetch.call_count == 1


def test_refetch_skipped_in_own_phase_without_openalex():
    with patch(_REFETCH, new_callable=AsyncMock) as refetch:
        run_pipeline.phase_fetch_truncated(
            run_pipeline.RunOptions(mode="full", sources={"hal", "scanr"})
        )
    assert refetch.call_count == 0
