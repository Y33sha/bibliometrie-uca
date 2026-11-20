"""Phase `structure_referentials` : référentiels ROR et HAL, lus par la reconnaissance des structures et par les pays.

- **Référentiel ROR** (`refresh_ror`) : importe la dernière version du dump ROR, si elle reste à importer.
- **Référentiel des structures HAL** (`refresh_hal_structures`) : charge les structures HAL citées et absentes du référentiel.

Chaque tâche met en file les contributions sources d'une organisation ou d'une structure qui change de pays.
"""

from __future__ import annotations

from collections.abc import Mapping

from pipeline.graph import Block, Phase, Task
from pipeline.http.polite_pool import default_user_agent
from pipeline.ingestion.complements.ror import ZenodoRorDumpSource
from pipeline.ingestion.hal.api import HalStructuresClient
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.structures.hal_structures import (
    HalStructureStore,
    run_refresh_hal_structures,
)
from pipeline.transformation.structures.ror import RorStore, run_refresh_ror


def _refresh_hal_structures(ctx: PhaseContext) -> PhaseMetrics:
    """Charge le référentiel des structures HAL."""
    with ctx.open_tx() as conn:
        return run_refresh_hal_structures(
            conn,
            source=HalStructuresClient(),
            store=HalStructureStore(conn),
            logger=ctx.logger,
            refresh_stale=ctx.options.policy.refresh_hal_structures,
        )


def _refresh_ror(ctx: PhaseContext) -> PhaseMetrics:
    """Rafraîchit le référentiel ROR depuis le dump publié sur Zenodo."""
    # Le dump est public : l'adresse du polite pool est facultative.
    source = ZenodoRorDumpSource(user_agent=default_user_agent(), logger=ctx.logger)
    with ctx.open_tx() as conn:
        return run_refresh_ror(conn, source=source, store=RorStore(conn), logger=ctx.logger)


REFRESH_ROR = Task(
    "refresh_ror",
    reads=("ror_dump_imports", "source_contribution_rors"),
    writes=(
        "ror_organizations",
        "ror_relations",
        "ror_dump_imports",
        # Dépendants d'une organisation qui change de pays.
        "source_contribution_countries_queue",
    ),
    previous_run=("ror_dump_imports",),
    network="zenodo",
    run=_refresh_ror,
    section="Référentiel ROR",
)


REFRESH_HAL_STRUCTURES = Task(
    "refresh_hal_structures",
    reads=("source_contribution_hal_structures",),
    writes=(
        "hal_structures",
        "hal_structure_relations",
        "hal_structure_aliases",
        # Contributions sources d'une structure qui change de pays.
        "source_contribution_countries_queue",
    ),
    previous_run=("hal_structures", "hal_structure_aliases"),
    network="hal",
    run=_refresh_hal_structures,
    section="Référentiel des structures HAL",
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie les métriques des deux tâches, avec leurs détails (`ror`, `hal_structures`)."""
    metrics = PhaseMetrics()
    for task_metrics in by_task.values():
        metrics.merge(task_metrics)
        metrics.details.update(task_metrics.details)
    return metrics


PHASE = Phase(
    "structure_referentials",
    "Référentiels ROR et HAL",
    (REFRESH_ROR, REFRESH_HAL_STRUCTURES),
    Block.SOURCE_RECORDS,
    assemble=assemble,
)
