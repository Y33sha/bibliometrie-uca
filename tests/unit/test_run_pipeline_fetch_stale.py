"""Régressions sur la phase `fetch_stale` / `_run_fetch_stale`.

1. WoS est opt-in (`--include-wos`) : exclu par défaut du refresh, comme
   `harvest` et `fetch_missing`.
2. Le refetch d'une source pose un circuit-breaker (coupe sur 429 répétés),
   au même titre que fetch_missing — sinon fetch_stale martèle une source
   à bout de budget API.
"""

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from pipeline.http.circuit_breaker import get_current_breaker
from pipeline.ingestion.common import fetch_stale
from pipeline.runtime.context import RunOptions
from pipeline.runtime.execution import phase_context
from pipeline.runtime.observability.metrics import PhaseMetrics


def _run_phase(options: RunOptions) -> PhaseMetrics:
    return fetch_stale.build().run(
        phase_context(
            options, credentials_missing=lambda _source: None, request_budget=lambda _source: None
        )
    )


def _called_targets(stack) -> MagicMock:
    """Patche les I/O de la phase `fetch_stale` et retourne le mock des sources refetch."""
    run_one = stack.enter_context(
        patch.object(fetch_stale, "_run_fetch_stale", return_value=PhaseMetrics())
    )
    # Fenêtre d'années : évite tout accès base (get_years lit la config).
    stack.enter_context(
        patch("pipeline.runtime.execution.get_sync_engine", return_value=MagicMock())
    )
    stack.enter_context(
        patch("pipeline.ingestion.common.fetch_stale.get_years", return_value=[2024])
    )
    return run_one


def test_fetch_stale_excludes_wos_by_default():
    with ExitStack() as stack:
        run_one = _called_targets(stack)
        _run_phase(RunOptions())
    targets = [c.args[1] for c in run_one.call_args_list]
    assert "wos" not in targets
    assert targets  # d'autres sources sont bien refetch


def test_fetch_stale_includes_wos_when_opted_in():
    with ExitStack() as stack:
        run_one = _called_targets(stack)
        _run_phase(RunOptions(include_wos=True))
    targets = [c.args[1] for c in run_one.call_args_list]
    assert "wos" in targets


def test_fetch_stale_covers_theses():
    # theses entre dans le refresh (refetch par id natif), contrairement à la
    # recherche par DOI de fetch_missing, qui l'exclut.
    with ExitStack() as stack:
        run_one = _called_targets(stack)
        _run_phase(RunOptions())
    assert "theses" in [c.args[1] for c in run_one.call_args_list]


def test_fetch_stale_couples_years_per_source():
    # theses ramène tout l'historique (borne None) ; les autres suivent la fenêtre du run.
    with ExitStack() as stack:
        run_one = _called_targets(stack)
        _run_phase(RunOptions())
    by_target = {c.args[1]: c.args[2] for c in run_one.call_args_list}
    assert by_target["theses"] is None
    assert by_target["hal"] == [2024]


def test_fetch_stale_year_narrows_all_including_theses():
    # `--year` cible une seule année pour toutes les sources, theses comprise.
    with ExitStack() as stack:
        run_one = _called_targets(stack)
        _run_phase(RunOptions(year=2023))
    by_target = {c.args[1]: c.args[2] for c in run_one.call_args_list}
    assert by_target["theses"] == [2023]
    assert by_target["hal"] == [2023]


def test_fetch_stale_respects_sources_filter():
    with ExitStack() as stack:
        run_one = _called_targets(stack)
        _run_phase(RunOptions(sources={"hal"}, include_wos=True))
    assert [c.args[1] for c in run_one.call_args_list] == ["hal"]


def test_la_relecture_d_une_source_tourne_sous_son_circuit_breaker():
    """L'exécuteur pose le circuit-breaker de la source pendant la relecture, puis le retire."""
    sources = []

    async def refresh(*_args, **_kwargs):
        breaker = get_current_breaker()
        sources.append(breaker and breaker.source)
        return PhaseMetrics()

    with ExitStack() as stack:
        stack.enter_context(patch("pipeline.ingestion.common.fetch_stale.refresh", new=refresh))
        stack.enter_context(
            patch("pipeline.runtime.execution.get_sync_engine", return_value=MagicMock())
        )
        stack.enter_context(
            patch("pipeline.ingestion.common.fetch_stale.get_years", return_value=[2024])
        )
        _run_phase(RunOptions(sources={"hal"}))

    assert sources == ["hal"]
    # La ContextVar est restaurée en sortie (pas de fuite de breaker).
    assert get_current_breaker() is None
