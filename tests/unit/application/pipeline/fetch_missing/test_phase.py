"""Orchestrateur de la phase `fetch_missing` : canaux HAL séquentiels + DOI parallèle, skip config.

Dépendances techniques injectées (runners par canal / par source, parallélisme, détection de
config), donc l'orchestrateur se teste sans I/O ni threads : `run_parallel` est remplacé par une
exécution synchrone déterministe.
"""

import logging

from application.pipeline.fetch_missing import phase
from application.pipeline.libelles import DERNIERE_BRANCHE
from application.pipeline.metrics import PhaseMetrics

_LOG = logging.getLogger("test")


def _sync_run_parallel(thunks):
    return {label: thunk() for label, thunk in thunks.items()}


def test_hal_channels_then_parallel_doi_with_skip():
    # sources=None → toutes les sources ; seule openalex est configurée côté DOI.
    metrics = phase.run(
        mode="full",
        sources=None,
        include_wos=False,
        fetch_hal_by_id=lambda: PhaseMetrics(new=2),
        fetch_hal_by_nnt=lambda: PhaseMetrics(new=1),
        fetch_doi_one=lambda source: PhaseMetrics(new=5),
        run_parallel=_sync_run_parallel,
        credentials_missing=lambda source: None if source == "openalex" else "pas de credentials",
        logger=_LOG,
    )

    channels = {r["key"] for r in metrics.details["table"]["rows"]}
    assert {"hal-id", "NNT", "openalex"} <= channels  # canaux HAL + DOI configurée
    assert "scanr" not in channels  # DOI non configurée → sautée
    assert any(s["code"] == "source_unconfigured" for s in metrics.signals)
    assert metrics.new == 8  # 2 (hal-id) + 1 (NNT) + 5 (openalex)


def test_nnt_channel_only_in_full_mode():
    calls: list[str] = []

    phase.run(
        mode="daily",
        sources=None,
        include_wos=False,
        fetch_hal_by_id=lambda: calls.append("id") or PhaseMetrics(),
        fetch_hal_by_nnt=lambda: calls.append("nnt") or PhaseMetrics(),
        fetch_doi_one=lambda source: PhaseMetrics(),
        run_parallel=_sync_run_parallel,
        credentials_missing=lambda source: "hors sujet ici",  # neutralise le volet DOI
        logger=_LOG,
    )

    assert calls == ["id"]  # NNT réservé au mode full


def _run_doi_only(fetch_doi_one, caplog) -> str:
    """Joue la seule recherche par DOI (HAL hors du filtre `sources`) et rend le journal."""
    with caplog.at_level(logging.INFO, logger=_LOG.name):
        phase.run(
            mode="daily",
            sources={"openalex", "scanr"},
            include_wos=False,
            fetch_hal_by_id=PhaseMetrics,
            fetch_hal_by_nnt=PhaseMetrics,
            fetch_doi_one=fetch_doi_one,
            run_parallel=_sync_run_parallel,
            credentials_missing=lambda source: None,
            logger=_LOG,
        )
    return caplog.text


def test_la_recherche_par_doi_sans_rien_a_chercher_le_dit(caplog):
    journal = _run_doi_only(lambda source: PhaseMetrics(), caplog)
    assert f"{DERNIERE_BRANCHE}Rien à faire" in journal


def test_une_source_qui_a_cherche_suffit_a_taire_le_rien_a_faire(caplog):
    journal = _run_doi_only(
        lambda source: PhaseMetrics(seen=3) if source == "openalex" else PhaseMetrics(), caplog
    )
    assert "Rien à faire" not in journal


def test_une_source_indisponible_n_est_pas_un_rien_a_faire(caplog):
    indisponible = PhaseMetrics(
        signals=[{"level": "warning", "code": "source_unavailable", "message": "openalex"}]
    )
    journal = _run_doi_only(
        lambda source: indisponible if source == "openalex" else PhaseMetrics(), caplog
    )
    assert "Rien à faire" not in journal


def test_hal_skipped_when_sources_excludes_it():
    calls: list[str] = []

    phase.run(
        mode="full",
        sources={"openalex"},  # pas de hal → canaux HAL sautés
        include_wos=False,
        fetch_hal_by_id=lambda: calls.append("id") or PhaseMetrics(),
        fetch_hal_by_nnt=lambda: calls.append("nnt") or PhaseMetrics(),
        fetch_doi_one=lambda source: PhaseMetrics(new=3),
        run_parallel=_sync_run_parallel,
        credentials_missing=lambda source: None,
        logger=_LOG,
    )

    assert calls == []  # aucun canal HAL
