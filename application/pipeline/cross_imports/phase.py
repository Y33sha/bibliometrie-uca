"""Orchestrateur de la phase `cross_imports` : rattrapage des documents repérés dans une source mais absents d'une autre. Deux mécanismes, dans cet ordre :

1. **Cross-import HAL** — deux canaux séquentiels : par hal-id (repéré dans OpenAlex/ScanR) et par NNT (thèses sans document HAL).
2. **Cross-import par DOI** — pour chaque source cible configurée, en parallèle : cherche les DOI vus ailleurs mais absents de la source et les fetche.
"""

import logging
from collections.abc import Callable
from functools import partial

from application.pipeline.metrics import PhaseMetrics
from application.pipeline.signals import filter_configured, timed_metrics
from application.ports.pipeline.parallel import RunParallel
from domain.sources.registry import DOI_SEARCHABLE_SOURCES

FetchChannel = Callable[[], PhaseMetrics]
"""Runner d'un canal HAL (hal-id ou NNT) : rend les métriques du canal."""
FetchDoiOne = Callable[[str], PhaseMetrics]
"""Runner du cross-import par DOI d'une source cible, sous circuit-breaker."""
CredentialsMissing = Callable[[str], "str | None"]
"""`(source) -> motif d'absence de credentials | None si configurée`."""


def _summary(metrics: PhaseMetrics, duration_s: float) -> dict[str, float]:
    """Ligne « par canal » de la table d'observabilité de la phase."""
    return {
        "interrogated": metrics.total,
        "new": metrics.new,
        "not_found": metrics.extras.get("not_found", 0),
        "duration_s": round(duration_s, 1),
    }


def run(
    *,
    mode: str,
    sources: set[str] | None,
    include_wos: bool,
    fetch_hal_by_id: FetchChannel,
    fetch_hal_by_nnt: FetchChannel,
    fetch_doi_one: FetchDoiOne,
    run_parallel: RunParallel,
    credentials_missing: CredentialsMissing,
    logger: logging.Logger,
) -> PhaseMetrics:
    """Enchaîne les canaux HAL puis le cross-import par DOI parallèle, et assemble les métriques."""
    metrics = PhaseMetrics()
    by_channel: dict[str, dict[str, float]] = {}

    # Étape 1 : cross-import HAL, deux canaux distincts (hal-id, NNT).
    if not sources or "hal" in sources:
        id_metrics, id_duration = timed_metrics(fetch_hal_by_id)
        metrics.merge(id_metrics)
        by_channel["hal-id"] = _summary(id_metrics, id_duration)

        if mode == "full":
            nnt_metrics, nnt_duration = timed_metrics(fetch_hal_by_nnt)
            metrics.merge(nnt_metrics)
            by_channel["NNT"] = _summary(nnt_metrics, nnt_duration)

    # Étape 2 : par DOI. WoS opt-in.
    targets = set(DOI_SEARCHABLE_SOURCES) - ({"wos"} if not include_wos else set())
    effective = (set(sources) if sources else set(targets)) & targets
    doi_targets = [t for t in DOI_SEARCHABLE_SOURCES if t in effective]
    configured = filter_configured(
        doi_targets,
        metrics,
        credentials_missing=credentials_missing,
        logger=logger,
        phase="cross_imports",
    )

    if configured:
        # Chaque source frappe une API distincte et écrit dans son propre staging — aucun état
        # partagé. La merge des métriques reste séquentielle (thread principal). Conséquence
        # assumée : la propagation cross-source d'un DOI fraîchement importé peut glisser au run
        # suivant (phase idempotente et auto-bornée).
        logger.info(
            "▶ cross-imports par DOI en parallèle (%d) : %s", len(configured), ", ".join(configured)
        )
        outcomes = run_parallel(
            {
                target: partial(timed_metrics, partial(fetch_doi_one, target))
                for target in configured
            }
        )
        for target, (channel_metrics, duration) in outcomes.items():
            metrics.merge(channel_metrics)
            by_channel[target] = _summary(channel_metrics, duration)

    if by_channel:
        metrics.details["table"] = {
            "rows": [{"key": channel, **summary} for channel, summary in by_channel.items()]
        }
    return metrics
