"""Phase `normalize` : normalisation de `staging` vers les enregistrements sources, les contributions sources et les adresses.

Les enregistrements sources sortent sans publication : la phase `publications` les y rattache. Pour HAL, les ORCID et IdRef sont lus dans le TEI.

La phase enchaîne ses tâches (`pipeline.graph`) :

1. la normalisation de chaque source retenue, dans l'ordre de `SOURCE_PRIORITY` ;
2. la suppression des enregistrements sources des documents disparus de leur source ;
3. la suppression des informations du contributeur qu'aucune contribution source ne référence : la normalisation réassigne des contributions sources, et la suppression précédente en retire ;
4. la suppression des adresses orphelines, pour la même raison.

L'exécuteur lance ensuite le `VACUUM` de `staging`, vidé de ses payloads : `VACUUM FULL` en mode full, simple dans les autres modes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from sqlalchemy import Connection

from domain.sources.registry import SOURCE_PRIORITY, source_label
from infrastructure.raw_store import NullRawStore, get_raw_store
from pipeline.ingestion.adapters import ADAPTERS
from pipeline.ingestion.common.adapter import SourceAdapter
from pipeline.ingestion.common.locations import LocationStore
from pipeline.ingestion.common.normalizer import (
    NormalizeStats,
    SourceNormalizer,
)
from pipeline.ingestion.common.source_contribution_store import (
    SourceContributionStore,
    delete_orphan_addresses,
    delete_orphan_contributor_information,
    mark_source_contributions_to_resync,
)
from pipeline.ingestion.common.source_records import (
    SourceRecordStore,
    delete_disappeared_source_records,
)
from pipeline.ingestion.common.staging import StagingStore
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.log_format import (
    LAST_BRANCH,
    quantity,
)
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import TaskRun, TaskStep, run_tasks
from pipeline.transformation.publishing.containers import ContainerStores
from pipeline.transformation.publishing.publishers.store import PublisherStore

NormalizeOne = Callable[[PhaseContext, str], NormalizeStats]
"""Normalise une source et rend son bilan."""


def _selected(source: str) -> Callable[[PhaseContext], bool]:
    """Condition d'exécution de la tâche de `source` : la source fait partie des sources du run."""
    return lambda ctx: source in ctx.options.sources


@dataclass(frozen=True)
class NormalizePhase:
    """Normalisation des sources du run, toutes quand il n'en restreint aucune, dans l'ordre de `SOURCE_PRIORITY`."""

    normalize_one: NormalizeOne
    prune_disappeared: Callable[[PhaseContext], int]
    cleanup_orphan_contributor_information: Callable[[PhaseContext], int]
    cleanup_orphan_addresses: Callable[[PhaseContext], int]

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute les tâches de la phase et assemble les métriques."""
        sources = [source.value for source in SOURCE_PRIORITY]
        steps = {
            f"normalize.{source}": TaskStep(
                self._normalize_task(source),
                label=source_label(source),
                progress_bar=True,
                when=_selected(source),
            )
            for source in sources
        }
        steps["normalize.prune_disappeared"] = TaskStep(self._prune)
        steps["normalize.cleanup_orphan_contributor_information"] = TaskStep(
            self._cleanup,
            section="Maintenance des tables",
            label="Informations du contributeur orphelines",
        )
        steps["normalize.cleanup_orphan_addresses"] = TaskStep(
            self._cleanup_addresses, section="Maintenance des tables", label="Adresses orphelines"
        )
        by_task = run_tasks("normalize", steps, ctx)

        rows = [
            {
                **cast("dict[str, object]", task.details["row"]),
                "duration_s": task.duration_s,
            }
            for source in sources
            if "row" in (task := by_task[f"normalize.{source}"]).details
        ]
        metrics = PhaseMetrics()
        normalized = sum(cast("int", row["processed"]) for row in rows)
        metrics.add(seen=normalized)
        metrics.details["table"] = {"rows": rows}
        metrics.details["disappeared_pruned"] = by_task["normalize.prune_disappeared"].extras.get(
            "disappeared", 0
        )
        return metrics

    def _normalize_task(self, source: str) -> TaskRun:
        """Tâche `normalize.<source>` : normalise la source et garde sa ligne de la table d'observabilité."""

        def run(ctx: PhaseContext) -> PhaseMetrics:
            stats = self.normalize_one(ctx, source)
            metrics = PhaseMetrics()
            metrics.details["row"] = {
                "key": source,
                "processed": stats.processed,
                "skipped": stats.skipped,
                "errors": stats.errors,
            }
            return metrics

        return run

    def _prune(self, ctx: PhaseContext) -> PhaseMetrics:
        """Supprime les documents disparus de leur source, et ferme la section de normalisation."""
        disappeared = self.prune_disappeared(ctx)
        if disappeared:
            ctx.logger.info(
                "%s%s (disparus de leur source)",
                LAST_BRANCH,
                quantity(disappeared, "document supprimé", "documents supprimés"),
            )
        else:
            ctx.logger.info("%saucun document disparu de sa source", LAST_BRANCH)
        return PhaseMetrics(extras={"disappeared": disappeared})

    def _cleanup(self, ctx: PhaseContext) -> PhaseMetrics:
        deleted = self.cleanup_orphan_contributor_information(ctx)
        metrics = PhaseMetrics()
        if deleted:
            metrics.report = f"{quantity(deleted, 'ligne supprimée', 'lignes supprimées')}"
        return metrics

    def _cleanup_addresses(self, ctx: PhaseContext) -> PhaseMetrics:
        deleted = self.cleanup_orphan_addresses(ctx)
        metrics = PhaseMetrics()
        if deleted:
            metrics.report = f"{quantity(deleted, 'adresse supprimée', 'adresses supprimées')}"
        return metrics


type NormalizerFactory = Callable[[Connection, logging.Logger], SourceNormalizer]


def build() -> Phase:
    return _NormalizeByOptions()


class _NormalizeByOptions:
    """Construit les normaliseurs selon les options du run (`--raw-store`), puis exécute `NormalizePhase`.

    Avec `--normalize-full`, chaque source marque d'abord tous ses enregistrements sources à resynchroniser.
    """

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        options = ctx.options
        registry = normalizer_builders(archive=options.raw_store)

        def normalize_one(ctx: PhaseContext, source: str) -> NormalizeStats:
            if options.normalize_full:
                _run_mark_source_contributions_to_resync(ctx, source)
            return _run_normalize(ctx, registry[source])

        return NormalizePhase(
            normalize_one=normalize_one,
            prune_disappeared=_run_prune_disappeared,
            cleanup_orphan_contributor_information=_run_cleanup_orphan_contributor_information,
            cleanup_orphan_addresses=_run_cleanup_orphan_addresses,
        ).run(ctx)


def _run_mark_source_contributions_to_resync(ctx: PhaseContext, source: str) -> None:
    with ctx.open_tx() as conn:
        mark_source_contributions_to_resync(conn, source)


def _run_prune_disappeared(ctx: PhaseContext) -> int:
    with ctx.open_tx() as conn:
        return delete_disappeared_source_records(conn)


def _run_cleanup_orphan_contributor_information(ctx: PhaseContext) -> int:
    with ctx.open_tx() as conn:
        return delete_orphan_contributor_information(conn)


def _run_cleanup_orphan_addresses(ctx: PhaseContext) -> int:
    with ctx.open_tx() as conn:
        return delete_orphan_addresses(conn)


def normalizer_builders(*, archive: bool = True) -> dict[str, NormalizerFactory]:
    """Constructeur du normaliseur de chaque source, sur les stores de la phase."""

    raw_store = get_raw_store() if archive else NullRawStore()

    def builder(adapter: SourceAdapter) -> NormalizerFactory:
        def build(conn: Connection, logger: logging.Logger) -> SourceNormalizer:
            return adapter.normalizer()(
                conn,
                logger,
                StagingStore(conn, raw_store),
                SourceRecordStore(conn),
                container_stores=ContainerStores.of(conn),
                publisher_store=PublisherStore(conn),
                contribution_store=SourceContributionStore(conn),
                location_store=LocationStore(conn),
            )

        return build

    return {source.value: builder(adapter) for source, adapter in ADAPTERS.items()}


def _run_normalize(ctx: PhaseContext, build: NormalizerFactory) -> NormalizeStats:
    with ctx.open_tx() as conn:
        return build(conn, ctx.logger).run()
