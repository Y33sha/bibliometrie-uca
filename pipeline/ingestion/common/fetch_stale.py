"""Phase `fetch_stale` : nouvelle lecture des documents de `staging` non revus par le moissonnage depuis `fetch_stale_after_days` jours. Une tâche par source, en parallèle.

Chaque document est relu par son identifiant natif :

- document trouvé → écriture dans `staging` ;
- document renvoyé sous un autre identifiant natif (work fusionné, DOI alias) → écriture dans `staging` du document renvoyé, document cherché marqué disparu (`disappeared_at`) ;
- absence confirmée (réponse valide, aucun document) → document marqué disparu ;
- source indisponible (réseau, 429, réponse illisible) → nouvelle tentative au run suivant.

Le délai étale la charge : chaque passe reprend seulement les documents qui viennent de le franchir.

La relecture se borne aux années moissonnées par le run ; une thèse en cours est relue quelle que soit la fenêtre. La phase est sautée dans un mode dont la policy l'exclut (`daily`). WoS est opt-in (`--include-wos`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from domain.config import ConfigKey
from domain.sources.registry import Source, source_label
from pipeline.graph import Task
from pipeline.ingestion.adapters import ADAPTERS
from pipeline.ingestion.common.stale_refetch import refresh
from pipeline.runtime.config import delay, window_years
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import skipped


def _years(ctx: PhaseContext) -> list[int] | None:
    """Renvoie les années de la fenêtre du run (`window_years`), ou `None` pour tout l'historique."""
    with ctx.open_tx() as conn:
        return window_years(conn, start_year=ctx.options.start_year, year=ctx.options.year)


def _run_fetch_stale(ctx: PhaseContext, target: str, years: list[int] | None) -> PhaseMetrics:
    """Relit les documents anciens d'une source, sur sa propre connexion."""
    refetch = ADAPTERS[Source(target)].stale_refetch()
    with ctx.open_tx() as conn:
        after_days = delay(conn, ConfigKey.FETCH_STALE_AFTER_DAYS)
        return asyncio.run(refresh(conn, refetch, ctx.logger, after_days=after_days, years=years))


TASKS = tuple(
    Task(
        str(source),
        reads=("config", "staging", "source_records.publication_year"),
        writes=("staging", "staging_normalization_queue"),
        previous_run=("staging", "source_records"),
        network=source,
        parallel_group="sources",
        run=lambda ctx, source=source: _run_fetch_stale(ctx, source, _years(ctx)),
        label=source_label(source),
        progress_bar=True,
        when=lambda ctx, source=source: source in ctx.options.queried_sources,
    )
    for source in Source
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie la somme des métriques des sources, avec la table des sources relues."""
    metrics = PhaseMetrics()
    by_source: dict[str, dict[str, float | None]] = {}
    for name, source_metrics in by_task.items():
        metrics.merge(source_metrics)
        if skipped(source_metrics):
            continue
        by_source[name] = {
            "interrogated": source_metrics.total,
            "refreshed": source_metrics.updated,
            "unchanged": source_metrics.unchanged,
            "disappeared": source_metrics.extras.get("disappeared", 0),
            "duration_s": source_metrics.duration_s,
        }
    if by_source:
        metrics.details["table"] = {
            "rows": [{"key": source, **summary} for source, summary in by_source.items()]
        }
    return metrics
