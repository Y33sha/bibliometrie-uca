"""Régressions sur la phase `fetch_stale` / `_run_fetch_stale`.

1. WoS est opt-in (`--include-wos`) : exclu par défaut du refresh, comme
   `extract` et `fetch_missing`.
2. Le refetch d'une source pose un circuit-breaker (coupe sur 429 répétés),
   au même titre que fetch_missing — sinon fetch_stale martèle une source
   à bout de budget API.
"""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

from application.pipeline.context import RunOptions
from application.pipeline.metrics import PhaseMetrics
from infrastructure.sources.circuit_breaker import (
    SourceCircuitBreaker,
    get_current_breaker,
)
from interfaces.cli.phases import fetch_stale
from interfaces.cli.phases.execution import phase_context


def _run_phase(options: RunOptions) -> PhaseMetrics:
    return fetch_stale.build().run(phase_context(options))


def _called_targets(stack) -> MagicMock:
    """Patche les I/O de la phase `fetch_stale` et retourne le mock des sources refetch."""
    run_one = stack.enter_context(
        patch.object(fetch_stale, "_run_fetch_stale", return_value=PhaseMetrics())
    )
    # Neutralise le gate de configuration (testé ailleurs) : ici on vérifie la
    # sélection des sources (opt-in WoS, filtre `sources`), pas la présence des
    # credentials — toutes les cibles sont réputées configurées.
    stack.enter_context(patch.object(fetch_stale, "credentials_missing", return_value=None))
    # Fenêtre d'années : évite tout accès base (get_years lit la config).
    stack.enter_context(patch("infrastructure.db.engine.get_sync_engine", return_value=MagicMock()))
    stack.enter_context(patch("infrastructure.sources.config.get_years", return_value=[2024]))
    return run_one


def test_fetch_stale_excludes_wos_by_default():
    with ExitStack() as stack:
        run_one = _called_targets(stack)
        _run_phase(RunOptions())
    targets = [c.args[0] for c in run_one.call_args_list]
    assert "wos" not in targets
    assert targets  # d'autres sources sont bien refetch


def test_fetch_stale_includes_wos_when_opted_in():
    with ExitStack() as stack:
        run_one = _called_targets(stack)
        _run_phase(RunOptions(include_wos=True))
    targets = [c.args[0] for c in run_one.call_args_list]
    assert "wos" in targets


def test_fetch_stale_covers_theses():
    # theses entre dans le refresh (refetch par id natif), contrairement à la
    # recherche par DOI de fetch_missing, qui l'exclut.
    with ExitStack() as stack:
        run_one = _called_targets(stack)
        _run_phase(RunOptions())
    assert "theses" in [c.args[0] for c in run_one.call_args_list]


def test_fetch_stale_couples_years_per_source():
    # theses ramène tout l'historique (borne None) ; les autres suivent la fenêtre du run.
    with ExitStack() as stack:
        run_one = _called_targets(stack)
        _run_phase(RunOptions())
    by_target = {c.args[0]: c.args[1] for c in run_one.call_args_list}
    assert by_target["theses"] is None
    assert by_target["hal"] == [2024]


def test_fetch_stale_year_narrows_all_including_theses():
    # `--year` cible une seule année pour toutes les sources, theses comprise.
    with ExitStack() as stack:
        run_one = _called_targets(stack)
        _run_phase(RunOptions(year=2023))
    by_target = {c.args[0]: c.args[1] for c in run_one.call_args_list}
    assert by_target["theses"] == [2023]
    assert by_target["hal"] == [2023]


def test_fetch_stale_respects_sources_filter():
    with ExitStack() as stack:
        run_one = _called_targets(stack)
        _run_phase(RunOptions(sources={"hal"}, include_wos=True))
    assert [c.args[0] for c in run_one.call_args_list] == ["hal"]


def test_run_fetch_stale_installs_circuit_breaker():
    with ExitStack() as stack:
        refresh = stack.enter_context(
            patch(
                "application.pipeline.extract.fetch_stale.refresh",
                new=AsyncMock(return_value=PhaseMetrics()),
            )
        )
        stack.enter_context(
            patch("infrastructure.db.engine.get_sync_engine", return_value=MagicMock())
        )
        stack.enter_context(
            patch.object(fetch_stale, "_make_fetch_stale_adapter", return_value=MagicMock())
        )
        fetch_stale._run_fetch_stale("hal", None)

    breaker = refresh.call_args.kwargs["breaker"]
    assert isinstance(breaker, SourceCircuitBreaker)
    # La ContextVar est restaurée en sortie (pas de fuite de breaker).
    assert get_current_breaker() is None
