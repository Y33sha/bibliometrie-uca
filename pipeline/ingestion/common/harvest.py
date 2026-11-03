"""Phase `harvest` : moissonnage des sources vers `staging`, une tâche par source, en parallèle.

La phase s'arrête en échec si le périmètre de moissonnage (`perimeter_extraction`) est vide. La policy du mode (`modes.py`) fixe les sources et la fenêtre :

- mode quotidien (`since_last`) : les documents modifiés depuis le dernier moissonnage quotidien réussi, à défaut depuis 30 jours ;
- autres modes : les années de `start_year` à l'année courante, ou la seule année `--year`.

Une source dont le périmètre d'interrogation manque est sautée avec un signal (`run_harvest`).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

from domain.dates import date_to_french, today
from domain.sources.registry import HARVESTED_SOURCES, Source, source_label
from infrastructure.observability.phase_executions import get_last_daily_harvest_date
from pipeline.graph import TaskRun, task
from pipeline.ingestion.adapters import ADAPTERS
from pipeline.ingestion.common.harvester import HarvestWindow, run_harvest
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import BRANCH
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import (
    select_targets,
    skipped,
)


def _source_summary(metrics: PhaseMetrics) -> dict[str, float | None]:
    """Renvoie la ligne « par source » de la table d'observabilité de la phase."""
    return {
        "found": metrics.total,
        "new": metrics.new,
        "updated": metrics.updated,
        "unchanged": metrics.unchanged,
        "errors": metrics.errors,
        "duration_s": metrics.duration_s,
    }


def _effective_sources(ctx: PhaseContext) -> set[str]:
    """Renvoie les sources moissonnées par le run : celles demandées, restreintes par le mode."""
    options = ctx.options
    effective = set(
        select_targets(HARVESTED_SOURCES, options.sources, include_wos=options.include_wos)
    )
    return effective & options.policy.harvest_sources


def _since_last_daily() -> tuple[date, str]:
    """Renvoie, pour le mode quotidien, la date de départ des modifications à moissonner, avec son origine.

    Cette date est celle du dernier moissonnage quotidien réussi, à défaut celle d'il y a 30 jours.
    """
    last = get_last_daily_harvest_date()
    if last is not None:
        return last, "dernier moissonnage quotidien réussi"
    return today() - timedelta(days=30), "aucun moissonnage quotidien réussi, repli sur 30 jours"


def _harvest(source: str) -> TaskRun:
    """Renvoie l'exécution du moissonnage de `source`, sur la fenêtre fixée par le mode."""

    def run(ctx: PhaseContext) -> PhaseMetrics:
        options = ctx.options
        since = None
        if options.policy.year_selection == "since_last":
            last_daily, origin = _since_last_daily()
            ctx.logger.info(
                "%sMode incrémental : enregistrements %s modifiés depuis le %s (%s)",
                BRANCH,
                source_label(source),
                date_to_french(last_daily),
                origin,
            )
            since = last_daily.isoformat()
        window = HarvestWindow(start_year=options.start_year, year=options.year, since=since)
        harvester = ADAPTERS[Source(source)].harvester
        assert harvester is not None, f"{source} : source moissonnée sans moissonneur"
        return run_harvest(ctx, "harvest", source, harvester, window)

    return run


# Acquisition : les canaux écrivent la dernière version de chaque document moissonné dans `staging`, dans un ordre indifférent. Leurs lectures de `staging` dédoublonnent et valent quel que soit l'ordre.
TASKS = tuple(
    task(
        f"harvest.{source}",
        reads=(
            "config",
            "structures",
            "perimeters",
            "perimeter_structures",
            "staging",
            "pipeline_phase_executions",
        ),
        writes=("staging", "staging_normalization_queue"),
        previous_run=("staging", "pipeline_phase_executions"),
        network=source,
        parallel_group="harvest",
        run=_harvest(source),
        label=source_label(source),
        progress_bar=True,
        threshold=5,
        when=lambda ctx, source=source: source in _effective_sources(ctx),
    )
    for source in HARVESTED_SOURCES
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie la somme des métriques des sources, avec la table des sources moissonnées."""
    metrics = PhaseMetrics()
    by_source: dict[str, dict[str, float | None]] = {}
    for name, source_metrics in by_task.items():
        metrics.merge(source_metrics)
        if not skipped(source_metrics):
            by_source[name.removeprefix("harvest.")] = _source_summary(source_metrics)
    if by_source:
        metrics.details["table"] = {
            "rows": [{"key": source, **summary} for source, summary in by_source.items()]
        }
    return metrics
