"""Régression : `refetch_truncated` tourne en début de `phase_normalize`,
pas en `phase_extract`.

Il cible les works OpenAlex staging à 100 auteurs `processed=FALSE` juste avant
que normalize ne les consomme — placement qui capte aussi les tronqués ramenés
par cross_imports et refresh_stale (cf. `phase_normalize`). Le placer en extract
(état antérieur) les ratait.
"""

from contextlib import ExitStack
from unittest.mock import patch

import run_pipeline
from application.pipeline.metrics import PhaseMetrics

_EXTRACTORS = (
    "_run_extract_openalex",
    "_run_extract_hal",
    "_run_extract_wos",
    "_run_extract_scanr",
    "_run_extract_theses",
)
_NORMALIZERS = (
    "_run_normalize_theses",
    "_run_normalize_crossref",
    "_run_normalize_scanr",
    "_run_normalize_hal",
    "_run_normalize_openalex",
    "_run_normalize_wos",
)


def _patch_all(stack, names, *, returns_metrics=False):
    for name in names:
        kw = {"return_value": PhaseMetrics()} if returns_metrics else {}
        stack.enter_context(patch.object(run_pipeline, name, **kw))


def test_refetch_not_called_in_extract():
    with ExitStack() as stack:
        _patch_all(stack, _EXTRACTORS, returns_metrics=True)
        refetch = stack.enter_context(
            patch.object(run_pipeline, "_run_refetch_truncated", return_value=PhaseMetrics())
        )
        run_pipeline.phase_extract(mode="full")
        assert refetch.call_count == 0


def test_refetch_called_in_normalize_when_openalex_present():
    with ExitStack() as stack:
        _patch_all(stack, _NORMALIZERS)
        stack.enter_context(patch.object(run_pipeline, "_vacuum_staging"))
        refetch = stack.enter_context(
            patch.object(run_pipeline, "_run_refetch_truncated", return_value=PhaseMetrics())
        )
        run_pipeline.phase_normalize(mode="full", sources={"openalex", "hal"})
        assert refetch.call_count == 1


def test_refetch_skipped_in_normalize_without_openalex():
    with ExitStack() as stack:
        _patch_all(stack, _NORMALIZERS)
        stack.enter_context(patch.object(run_pipeline, "_vacuum_staging"))
        refetch = stack.enter_context(
            patch.object(run_pipeline, "_run_refetch_truncated", return_value=PhaseMetrics())
        )
        run_pipeline.phase_normalize(mode="full", sources={"hal", "scanr"})
        assert refetch.call_count == 0
