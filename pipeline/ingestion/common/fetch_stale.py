"""Phase `fetch_stale` : nouvelle recherche des documents de `staging` non revus par le moissonnage depuis le délai de leur source (`fetch_stale_after_days`). Une tâche par source, en parallèle.

Chaque document est cherché par son identifiant natif :

- document trouvé → écriture dans `staging` ;
- document renvoyé sous un autre identifiant natif (work fusionné, DOI alias) → écriture dans `staging` du document renvoyé, document cherché marqué disparu (`disappeared_at`) ;
- absence confirmée (réponse valide, aucun document) → document marqué disparu ;
- source indisponible (réseau, 429, réponse illisible) → nouvelle tentative au run suivant.

Le délai étale la charge : chaque passe reprend seulement les documents qui viennent de le franchir. Le plafond `fetch_stale_max_per_source` borne le nombre de documents cherchés par source. Les documents revus depuis le plus longtemps passent en premier.

La recherche se borne aux années moissonnées par le run. Une thèse en cours est cherchée quelle que soit la fenêtre.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from domain.config import ConfigKey
from domain.sources.registry import Source, source_label
from pipeline.graph import Block, Phase, Task
from pipeline.ingestion.adapters import adapter
from pipeline.ingestion.common.stale_refetch import refresh
from pipeline.runtime.config import cap, delay_for_source, window_years
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import assemble_by_source


def _years(ctx: PhaseContext) -> list[int]:
    """Renvoie les années de la fenêtre du run (`window_years`)."""
    with ctx.open_tx() as conn:
        return window_years(conn, ctx.options.years)


def _run_fetch_stale(ctx: PhaseContext, target: str, years: list[int]) -> PhaseMetrics:
    """Cherche de nouveau les documents anciens d'une source, sur sa propre connexion."""
    fetch_one = adapter(Source(target)).fetch_by_native_id
    with ctx.open_tx() as conn:
        after_days = delay_for_source(conn, ConfigKey.FETCH_STALE_AFTER_DAYS, target)
        limit = cap(conn, ConfigKey.FETCH_STALE_MAX_PER_SOURCE)
        return asyncio.run(
            refresh(
                conn,
                target,
                fetch_one,
                ctx.logger,
                after_days=after_days,
                years=years,
                limit=limit,
            )
        )


_CHILDREN = tuple(
    Task(
        str(source),
        reads=("config", "staging", "source_records.publication_year"),
        writes=("staging", "staging_normalization_queue"),
        previous_runs=("staging", "source_records"),
        network=source,
        parallel_group="sources",
        run=lambda ctx, source=source: _run_fetch_stale(ctx, source, _years(ctx)),
        label=source_label(source),
        when=lambda ctx, source=source: source in ctx.options.sources,
    )
    for source in Source
)


def _summary(metrics: PhaseMetrics) -> dict[str, float | None]:
    """Renvoie la ligne « par source » de la table d'observabilité de la phase."""
    return {
        "interrogated": metrics.total,
        "refreshed": metrics.updated,
        # Document renvoyé sous un autre identifiant natif que celui cherché.
        "new": metrics.new,
        "unchanged": metrics.unchanged,
        "disappeared": metrics.extras.get("disappeared", 0),
        "duration_s": metrics.duration_s,
    }


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie la somme des métriques des sources, avec la table des sources interrogées."""
    return assemble_by_source(by_task, _summary)


PHASE = Phase(
    "fetch_stale",
    "Recherche des documents non revus par le moissonnage",
    _CHILDREN,
    Block.HARVESTING,
    when=lambda ctx: ctx.options.policy.fetch_stale,
    assemble=assemble,
    total_line=True,
)
