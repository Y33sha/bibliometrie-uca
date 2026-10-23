"""Orchestrateur de la phase `fetch_missing` : canaux HAL séquentiels, puis lot parallèle de la recherche par DOI.

Les dépendances techniques sont injectées (runners par canal et par source, parallélisme). L'orchestrateur se teste donc sans I/O ni threads : `run_parallel` est remplacé par une exécution synchrone déterministe.
"""

import logging

from pipeline.ingestion.common.fetch_missing import FetchMissingPhase
from pipeline.runtime.observability.log_format import LAST_BRANCH
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import signal_source_unconfigured


def _sync_run_parallel(thunks):
    return {label: thunk() for label, thunk in thunks.items()}


def _non_configuree(source: str) -> PhaseMetrics:
    """Métriques que rend l'accès à une source sans identifiants."""
    metrics = PhaseMetrics()
    signal_source_unconfigured(
        metrics, source, "pas de credentials", logger=logging.getLogger("test"), phase="test"
    )
    return metrics


def test_hal_channels_then_parallel_doi_with_skip(contexte):
    # Toutes les sources, par défaut ; seule openalex est configurée côté DOI.
    metrics = FetchMissingPhase(
        fetch_hal_by_id=lambda _ctx: PhaseMetrics(new=2),
        fetch_hal_by_nnt=lambda _ctx: PhaseMetrics(new=1),
        fetch_theses_by_nnt=lambda _ctx: PhaseMetrics(),
        fetch_doi_one=lambda _ctx, source: (
            PhaseMetrics(new=5) if source == "openalex" else _non_configuree(source)
        ),
        run_parallel=_sync_run_parallel,
    ).run(contexte(mode="full"))

    channels = {r["key"] for r in metrics.details["table"]["rows"]}
    assert {"hal-id", "NNT", "openalex"} <= channels  # canaux HAL + DOI configurée
    assert "scanr" not in channels  # DOI non configurée → sautée
    assert any(s["code"] == "source_unconfigured" for s in metrics.signals)
    assert metrics.new == 8  # 2 (hal-id) + 1 (NNT) + 5 (openalex)


def test_nnt_channel_only_in_full_mode(contexte):
    calls: list[str] = []

    FetchMissingPhase(
        fetch_hal_by_id=lambda _ctx: calls.append("id") or PhaseMetrics(),
        fetch_hal_by_nnt=lambda _ctx: calls.append("nnt") or PhaseMetrics(),
        fetch_theses_by_nnt=lambda _ctx: PhaseMetrics(),
        fetch_doi_one=lambda _ctx, source: PhaseMetrics(),
        run_parallel=_sync_run_parallel,
    ).run(contexte(mode="daily"))

    assert calls == ["id"]  # NNT réservé au mode full


def _run_doi_only(contexte, fetch_doi_one, caplog) -> str:
    """Joue la seule recherche par DOI (HAL hors du filtre `sources`) et rend le journal."""
    with caplog.at_level(logging.INFO, logger="test"):
        FetchMissingPhase(
            fetch_hal_by_id=lambda _ctx: PhaseMetrics(),
            fetch_hal_by_nnt=lambda _ctx: PhaseMetrics(),
            fetch_theses_by_nnt=lambda _ctx: PhaseMetrics(),
            fetch_doi_one=fetch_doi_one,
            run_parallel=_sync_run_parallel,
        ).run(contexte(mode="daily", sources={"openalex", "scanr"}))
    return caplog.text


def test_la_recherche_par_doi_sans_rien_a_chercher_le_dit(contexte, caplog):
    journal = _run_doi_only(contexte, lambda _ctx, source: PhaseMetrics(), caplog)
    assert f"{LAST_BRANCH}Rien à faire" in journal


def test_une_source_qui_a_cherche_suffit_a_taire_le_rien_a_faire(contexte, caplog):
    journal = _run_doi_only(
        contexte,
        lambda _ctx, source: PhaseMetrics(seen=3) if source == "openalex" else PhaseMetrics(),
        caplog,
    )
    assert "Rien à faire" not in journal


def test_une_source_indisponible_n_est_pas_un_rien_a_faire(contexte, caplog):
    indisponible = PhaseMetrics(
        signals=[{"level": "warning", "code": "source_unavailable", "message": "openalex"}]
    )
    journal = _run_doi_only(
        contexte,
        lambda _ctx, source: indisponible if source == "openalex" else PhaseMetrics(),
        caplog,
    )
    assert "Rien à faire" not in journal


def test_theses_channel_suit_le_filtre_des_sources(contexte):
    calls: list[str] = []

    def phase() -> FetchMissingPhase:
        return FetchMissingPhase(
            fetch_hal_by_id=lambda _ctx: PhaseMetrics(),
            fetch_hal_by_nnt=lambda _ctx: PhaseMetrics(),
            fetch_theses_by_nnt=lambda _ctx: calls.append("theses") or PhaseMetrics(),
            fetch_doi_one=lambda _ctx, source: PhaseMetrics(),
            run_parallel=_sync_run_parallel,
        )

    phase().run(contexte(mode="daily", sources={"openalex"}))
    assert calls == []
    phase().run(contexte(mode="daily", sources={"theses"}))
    assert calls == ["theses"]


def test_hal_skipped_when_sources_excludes_it(contexte):
    calls: list[str] = []

    FetchMissingPhase(
        fetch_hal_by_id=lambda _ctx: calls.append("id") or PhaseMetrics(),
        fetch_hal_by_nnt=lambda _ctx: calls.append("nnt") or PhaseMetrics(),
        fetch_theses_by_nnt=lambda _ctx: PhaseMetrics(),
        fetch_doi_one=lambda _ctx, source: PhaseMetrics(new=3),
        run_parallel=_sync_run_parallel,
    ).run(contexte(mode="full", sources={"openalex"}))  # pas de hal → canaux HAL sautés

    assert calls == []  # aucun canal HAL
