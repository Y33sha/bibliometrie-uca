"""Régression : `refetch_truncated` est une phase distincte, placée entre
`refresh_stale` et `normalize` (ni dans `phase_extract`, ni dans `phase_normalize`).

Elle cible les works OpenAlex staging à 100 auteurs `processed=FALSE` juste avant
que normalize ne les consomme — placement qui capte aussi les tronqués ramenés
par cross_imports et refresh_stale. La placer en extract (état antérieur) les
ratait ; la garder dans normalize mêlait un fetch réseau à une phase de
transformation.
"""

from contextlib import ExitStack
from unittest.mock import patch

import run_pipeline
from application.pipeline.metrics import PhaseMetrics


def test_refetch_not_called_in_extract():
    with ExitStack() as stack:
        stack.enter_context(patch.object(run_pipeline, "_run_extract", return_value=PhaseMetrics()))
        refetch = stack.enter_context(
            patch.object(run_pipeline, "_run_refetch_truncated", return_value=PhaseMetrics())
        )
        run_pipeline.phase_extract(mode="full")
        assert refetch.call_count == 0


def test_refetch_not_called_in_normalize():
    with ExitStack() as stack:
        stack.enter_context(patch.object(run_pipeline, "_run_normalize"))
        stack.enter_context(patch.object(run_pipeline, "_vacuum_staging"))
        stack.enter_context(patch.object(run_pipeline, "_run_cleanup_orphan_identities"))
        refetch = stack.enter_context(
            patch.object(run_pipeline, "_run_refetch_truncated", return_value=PhaseMetrics())
        )
        run_pipeline.phase_normalize(mode="full", sources={"openalex", "hal"})
        assert refetch.call_count == 0


def test_refetch_called_in_own_phase_when_openalex_present():
    with ExitStack() as stack:
        refetch = stack.enter_context(
            patch.object(run_pipeline, "_run_refetch_truncated", return_value=PhaseMetrics())
        )
        run_pipeline.phase_refetch_truncated(mode="full", sources={"openalex", "hal"})
        assert refetch.call_count == 1


def test_refetch_skipped_in_own_phase_without_openalex():
    with ExitStack() as stack:
        refetch = stack.enter_context(
            patch.object(run_pipeline, "_run_refetch_truncated", return_value=PhaseMetrics())
        )
        run_pipeline.phase_refetch_truncated(mode="full", sources={"hal", "scanr"})
        assert refetch.call_count == 0
