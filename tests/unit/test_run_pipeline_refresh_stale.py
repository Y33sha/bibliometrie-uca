"""Régressions sur `phase_refresh_stale` / `_run_refresh_stale`.

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


def _called_targets(stack) -> MagicMock:
    """Patche les I/O de `phase_refresh_stale` et retourne le mock des sources refetch."""
    run_one = stack.enter_context(
        patch.object(run_pipeline, "_run_refresh_stale", return_value=PhaseMetrics())
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
    return run_one


def test_refresh_stale_excludes_wos_by_default():
    with ExitStack() as stack:
        run_one = _called_targets(stack)
        run_pipeline.phase_refresh_stale()
    targets = [c.args[0] for c in run_one.call_args_list]
    assert "wos" not in targets
    assert targets  # d'autres sources sont bien refetch


def test_refresh_stale_includes_wos_when_opted_in():
    with ExitStack() as stack:
        run_one = _called_targets(stack)
        run_pipeline.phase_refresh_stale(include_wos=True)
    targets = [c.args[0] for c in run_one.call_args_list]
    assert "wos" in targets


def test_refresh_stale_covers_theses():
    # theses entre dans le refresh (refetch par id natif), contrairement au
    # cross-import par DOI qui l'excluait.
    with ExitStack() as stack:
        run_one = _called_targets(stack)
        run_pipeline.phase_refresh_stale()
    assert "theses" in [c.args[0] for c in run_one.call_args_list]


def test_refresh_stale_respects_sources_filter():
    with ExitStack() as stack:
        run_one = _called_targets(stack)
        run_pipeline.phase_refresh_stale(sources={"hal"}, include_wos=True)
    assert [c.args[0] for c in run_one.call_args_list] == ["hal"]


def test_run_refresh_stale_installs_circuit_breaker():
    with ExitStack() as stack:
        refresh = stack.enter_context(
            patch(
                "application.pipeline.extract.refresh_stale.refresh",
                new=AsyncMock(return_value=PhaseMetrics()),
            )
        )
        stack.enter_context(
            patch("infrastructure.db.engine.get_sync_engine", return_value=MagicMock())
        )
        stack.enter_context(
            patch.object(run_pipeline, "_make_refresh_stale_adapter", return_value=MagicMock())
        )
        run_pipeline._run_refresh_stale("hal")

    breaker = refresh.call_args.kwargs["breaker"]
    assert isinstance(breaker, SourceCircuitBreaker)
    # La ContextVar est restaurée en sortie (pas de fuite de breaker).
    assert get_current_breaker() is None
