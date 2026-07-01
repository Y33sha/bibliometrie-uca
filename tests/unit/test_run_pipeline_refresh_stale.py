"""Régressions sur `phase_refresh_stale` / `_run_refresh_stale_doi`.

1. WoS est opt-in (`--include-wos`) : exclu par défaut du refresh, comme
   `extract` et `cross_imports`.
2. Le refetch d'une source pose un circuit-breaker (coupe sur 429 répétés),
   au même titre que le cross-import — sinon refresh_stale martèle une source
   à bout de budget API.
"""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import run_pipeline
from application.pipeline.metrics import PhaseMetrics
from infrastructure.sources.circuit_breaker import (
    SourceCircuitBreaker,
    get_current_breaker,
)


def _called_targets(stack) -> list[str]:
    """Patche les I/O de `phase_refresh_stale` et retourne les sources refetch."""
    doi = stack.enter_context(
        patch.object(run_pipeline, "_run_refresh_stale_doi", return_value=PhaseMetrics())
    )
    stack.enter_context(patch("infrastructure.db.engine.get_sync_engine", return_value=MagicMock()))
    stack.enter_context(
        patch(
            "infrastructure.sources.common.mark_undiscoverable_stale_disappeared",
            return_value={},
        )
    )
    # Neutralise le gate de configuration (testé ailleurs) : ici on vérifie la
    # sélection des sources (opt-in WoS, filtre `sources`), pas la présence des
    # credentials — le passthrough laisse passer toutes les cibles.
    stack.enter_context(
        patch.object(
            run_pipeline,
            "_configured_api_targets",
            side_effect=lambda targets, metrics, *, phase: targets,
        )
    )
    return doi


def test_refresh_stale_excludes_wos_by_default():
    with ExitStack() as stack:
        doi = _called_targets(stack)
        run_pipeline.phase_refresh_stale()
    targets = [c.args[0] for c in doi.call_args_list]
    assert "wos" not in targets
    assert targets  # d'autres sources sont bien refetch


def test_refresh_stale_includes_wos_when_opted_in():
    with ExitStack() as stack:
        doi = _called_targets(stack)
        run_pipeline.phase_refresh_stale(include_wos=True)
    targets = [c.args[0] for c in doi.call_args_list]
    assert "wos" in targets


def test_refresh_stale_respects_sources_filter():
    with ExitStack() as stack:
        doi = _called_targets(stack)
        run_pipeline.phase_refresh_stale(sources={"hal"}, include_wos=True)
    assert [c.args[0] for c in doi.call_args_list] == ["hal"]


def test_refresh_stale_doi_installs_circuit_breaker():
    with ExitStack() as stack:
        run_async = stack.enter_context(
            patch(
                "application.pipeline.extract.fetch_missing_doi.run_async",
                new=AsyncMock(return_value=PhaseMetrics()),
            )
        )
        stack.enter_context(
            patch("infrastructure.db.engine.get_sync_engine", return_value=MagicMock())
        )
        stack.enter_context(
            patch.object(run_pipeline, "_make_fetch_missing_doi_adapter", return_value=MagicMock())
        )
        run_pipeline._run_refresh_stale_doi("hal")

    breaker = run_async.call_args.kwargs["breaker"]
    assert isinstance(breaker, SourceCircuitBreaker)
    # La ContextVar est restaurée en sortie (pas de fuite de breaker).
    assert get_current_breaker() is None
