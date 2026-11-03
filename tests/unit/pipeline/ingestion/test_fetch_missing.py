"""Phase `fetch_missing` : canaux par hal-id et par NNT, puis lot parallèle de la recherche par DOI.

Les fonctions des tâches sont remplacées : la phase se teste sans I/O.
"""

import dataclasses
import logging
from collections.abc import Callable

from pipeline.graph import Phase
from pipeline.phases import PHASES
from pipeline.runtime.observability.log_format import LAST_BRANCH
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import signal_source_unconfigured
from pipeline.task_runner import run_phase

_FETCH_MISSING = next(phase for phase in PHASES if phase.name == "fetch_missing")

type Channel = Callable[..., PhaseMetrics]


def _vide(*_args) -> PhaseMetrics:
    return PhaseMetrics()


class FetchMissingPhase:
    """Phase `fetch_missing`, chaque canal exécuté par la fonction donnée."""

    def __init__(
        self,
        *,
        fetch_hal_by_id: Channel = _vide,
        fetch_scanr_by_hal_id: Channel = _vide,
        fetch_hal_by_nnt: Channel = _vide,
        fetch_theses_by_nnt: Channel = _vide,
        fetch_doi_one: Channel = _vide,
    ) -> None:
        runs = {
            "fetch_missing.hal_by_id": fetch_hal_by_id,
            "fetch_missing.scanr_by_hal_id": fetch_scanr_by_hal_id,
            "fetch_missing.hal_by_nnt": fetch_hal_by_nnt,
            "fetch_missing.theses_by_nnt": fetch_theses_by_nnt,
        }

        def run(name: str) -> Channel:
            if name in runs:
                return runs[name]
            target = name.removeprefix("fetch_missing.doi.")
            return lambda ctx: fetch_doi_one(ctx, target)

        self.phase: Phase = dataclasses.replace(
            _FETCH_MISSING,
            tasks=tuple(dataclasses.replace(t, run=run(t.name)) for t in _FETCH_MISSING.tasks),
        )

    def run(self, ctx) -> PhaseMetrics:
        return run_phase(self.phase, ctx)


def _non_configuree(source: str) -> PhaseMetrics:
    """Renvoie les métriques de l'accès à une source sans identifiants."""
    metrics = PhaseMetrics()
    signal_source_unconfigured(
        metrics, source, "pas de credentials", logger=logging.getLogger("test"), phase="test"
    )
    return metrics


def test_hal_channels_then_parallel_doi_with_skip(contexte):
    # Toutes les sources, par défaut ; seule openalex est configurée côté DOI.
    metrics = FetchMissingPhase(
        fetch_hal_by_id=lambda _ctx: PhaseMetrics(new=2),
        fetch_scanr_by_hal_id=lambda _ctx: PhaseMetrics(),
        fetch_hal_by_nnt=lambda _ctx: PhaseMetrics(new=1),
        fetch_theses_by_nnt=lambda _ctx: PhaseMetrics(),
        fetch_doi_one=lambda _ctx, source: (
            PhaseMetrics(new=5) if source == "openalex" else _non_configuree(source)
        ),
    ).run(contexte(mode="full"))

    channels = {r["key"] for r in metrics.details["table"]["rows"]}
    assert {
        "hal-id",
        "NNT",
        "openalex",
    } <= channels  # canaux HAL et source configurée pour la recherche par DOI
    assert "scanr" not in channels  # source non configurée pour la recherche par DOI : sautée
    assert any(s["code"] == "source_unconfigured" for s in metrics.signals)
    assert metrics.new == 8  # 2 (hal-id) + 1 (NNT) + 5 (openalex)


def test_nnt_channel_only_in_full_mode(contexte):
    calls: list[str] = []

    FetchMissingPhase(
        fetch_hal_by_id=lambda _ctx: calls.append("id") or PhaseMetrics(),
        fetch_scanr_by_hal_id=lambda _ctx: PhaseMetrics(),
        fetch_hal_by_nnt=lambda _ctx: calls.append("nnt") or PhaseMetrics(),
        fetch_theses_by_nnt=lambda _ctx: PhaseMetrics(),
        fetch_doi_one=lambda _ctx, source: PhaseMetrics(),
    ).run(contexte(mode="daily"))

    assert calls == ["id"]  # NNT réservé au mode full


def _run_doi_only(contexte, fetch_doi_one, caplog) -> str:
    """Joue la seule recherche par DOI (HAL hors du filtre `sources`) et renvoie le journal."""
    with caplog.at_level(logging.INFO, logger="test"):
        FetchMissingPhase(
            fetch_hal_by_id=lambda _ctx: PhaseMetrics(),
            fetch_scanr_by_hal_id=lambda _ctx: PhaseMetrics(),
            fetch_hal_by_nnt=lambda _ctx: PhaseMetrics(),
            fetch_theses_by_nnt=lambda _ctx: PhaseMetrics(),
            fetch_doi_one=fetch_doi_one,
        ).run(contexte(mode="daily", sources={"openalex", "crossref"}))
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


def test_les_recherches_par_nnt_sans_rien_a_chercher_ferment_leur_section_une_fois(
    contexte, caplog
):
    """Les recherches par NNT dans HAL et dans theses.fr partagent une section : une seule ligne « Rien à faire » la ferme."""
    with caplog.at_level(logging.INFO, logger="test"):
        FetchMissingPhase(
            fetch_hal_by_id=lambda _ctx: PhaseMetrics(seen=2),
            fetch_scanr_by_hal_id=lambda _ctx: PhaseMetrics(),
            fetch_hal_by_nnt=lambda _ctx: PhaseMetrics(),
            fetch_theses_by_nnt=lambda _ctx: PhaseMetrics(),
            fetch_doi_one=lambda _ctx, source: PhaseMetrics(seen=1),
        ).run(contexte(mode="full", sources={"hal", "theses"}))

    messages = caplog.messages
    section = messages.index("▶ Recherche par NNT des thèses trouvées ailleurs")
    assert messages[section + 1] == f"{LAST_BRANCH}Rien à faire"
    assert messages.count(f"{LAST_BRANCH}Rien à faire") == 1


def test_theses_channel_suit_le_filtre_des_sources(contexte):
    calls: list[str] = []

    def phase() -> FetchMissingPhase:
        return FetchMissingPhase(
            fetch_hal_by_id=lambda _ctx: PhaseMetrics(),
            fetch_scanr_by_hal_id=lambda _ctx: PhaseMetrics(),
            fetch_hal_by_nnt=lambda _ctx: PhaseMetrics(),
            fetch_theses_by_nnt=lambda _ctx: calls.append("theses") or PhaseMetrics(),
            fetch_doi_one=lambda _ctx, source: PhaseMetrics(),
        )

    phase().run(contexte(mode="daily", sources={"openalex"}))
    assert calls == []
    phase().run(contexte(mode="daily", sources={"theses"}))
    assert calls == ["theses"]


def test_hal_skipped_when_sources_excludes_it(contexte):
    calls: list[str] = []

    FetchMissingPhase(
        fetch_hal_by_id=lambda _ctx: calls.append("id") or PhaseMetrics(),
        fetch_scanr_by_hal_id=lambda _ctx: PhaseMetrics(),
        fetch_hal_by_nnt=lambda _ctx: calls.append("nnt") or PhaseMetrics(),
        fetch_theses_by_nnt=lambda _ctx: PhaseMetrics(),
        fetch_doi_one=lambda _ctx, source: PhaseMetrics(new=3),
    ).run(contexte(mode="full", sources={"openalex"}))  # HAL hors du filtre : canaux HAL sautés

    assert calls == []  # aucun canal HAL


def test_les_recherches_par_hal_id_partagent_une_section(contexte, caplog):
    """Les recherches par hal-id dans HAL et dans ScanR partagent une section, et chacune suit le filtre des sources."""
    calls: list[str] = []

    def phase() -> FetchMissingPhase:
        return FetchMissingPhase(
            fetch_hal_by_id=lambda _ctx: calls.append("hal") or PhaseMetrics(),
            fetch_scanr_by_hal_id=lambda _ctx: calls.append("scanr") or PhaseMetrics(),
            fetch_hal_by_nnt=lambda _ctx: PhaseMetrics(),
            fetch_theses_by_nnt=lambda _ctx: PhaseMetrics(),
            fetch_doi_one=lambda _ctx, source: PhaseMetrics(seen=1),
        )

    with caplog.at_level(logging.INFO, logger="test"):
        phase().run(contexte(mode="daily", sources={"hal", "scanr"}))
    assert sorted(calls) == ["hal", "scanr"]
    messages = caplog.messages
    section = messages.index("▶ Recherche des documents avec hal-id trouvés ailleurs")
    assert messages[section + 1] == f"{LAST_BRANCH}Rien à faire"

    calls.clear()
    phase().run(contexte(mode="daily", sources={"scanr"}))
    assert calls == ["scanr"]
