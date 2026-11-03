"""Phase `normalize` : normalisation de `staging` vers les enregistrements sources, les contributions sources et les adresses.

Les enregistrements sources sont écrits sans publication. La phase `publications` les rattache à une publication. Pour HAL, les ORCID et IdRef sont lus dans le TEI.

Tâches de la phase, dans l'ordre (`pipeline.graph`) :

1. la normalisation de chaque source retenue, dans l'ordre de `SOURCE_PRIORITY` ;
2. la suppression des enregistrements sources des documents disparus de leur source ;
3. la suppression des informations du contributeur sans contribution source : la normalisation réassigne des contributions sources, et l'étape précédente supprime des contributions sources ;
4. la suppression des adresses orphelines, pour la même raison.

L'exécuteur lance ensuite le `VACUUM` de `staging`, vidé de ses payloads : `VACUUM FULL` en mode full, simple dans les autres modes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import cast

from sqlalchemy import Connection

from domain.sources.registry import SOURCE_PRIORITY, source_label
from infrastructure.raw_store import NullRawStore, get_raw_store
from pipeline.graph import TaskRun, task
from pipeline.ingestion.adapters import ADAPTERS
from pipeline.ingestion.common.adapter import SourceAdapter
from pipeline.ingestion.common.embargoes import EmbargoStore
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
from pipeline.ingestion.common.subjects import SourceRecordSubjectStore
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import (
    LAST_BRANCH,
    quantity,
)
from pipeline.runtime.observability.metrics import PhaseMetrics


def _normalize_one(ctx: PhaseContext, source: str) -> NormalizeStats:
    """Normalise une source. Avec `--normalize-full`, marque d'abord tous ses enregistrements sources à resynchroniser. Avec `--raw-store`, archive les payloads."""
    if ctx.options.normalize_full:
        _run_mark_source_contributions_to_resync(ctx, source)
    return _run_normalize(ctx, normalizer_builders(archive=ctx.options.raw_store)[source])


def _normalize(source: str) -> TaskRun:
    """Renvoie la tâche `normalize.<source>`, qui normalise la source et garde sa ligne de la table d'observabilité."""

    def run(ctx: PhaseContext) -> PhaseMetrics:
        stats = _normalize_one(ctx, source)
        metrics = PhaseMetrics()
        metrics.report = _report(stats)
        metrics.details["row"] = {
            "key": source,
            "processed": stats.processed,
            "skipped": stats.skipped,
            "errors": stats.errors,
        }
        return metrics

    return run


def _prune(ctx: PhaseContext) -> PhaseMetrics:
    """Supprime les enregistrements sources des documents disparus de leur source, et ferme la section de normalisation."""
    disappeared = _run_prune_disappeared(ctx)
    if disappeared:
        ctx.logger.info(
            "%s%s (disparus de leur source)",
            LAST_BRANCH,
            quantity(disappeared, "document supprimé", "documents supprimés"),
        )
    else:
        ctx.logger.info("%saucun document disparu de sa source", LAST_BRANCH)
    return PhaseMetrics(extras={"disappeared": disappeared})


def _cleanup_contributor_information(ctx: PhaseContext) -> PhaseMetrics:
    deleted = _run_cleanup_orphan_contributor_information(ctx)
    metrics = PhaseMetrics()
    if deleted:
        metrics.report = f"{quantity(deleted, 'ligne supprimée', 'lignes supprimées')}"
    return metrics


def _cleanup_addresses(ctx: PhaseContext) -> PhaseMetrics:
    deleted = _run_cleanup_orphan_addresses(ctx)
    metrics = PhaseMetrics()
    if deleted:
        metrics.report = f"{quantity(deleted, 'adresse supprimée', 'adresses supprimées')}"
    return metrics


def _report(stats: NormalizeStats) -> str | None:
    """Renvoie la ligne de bilan d'une source : documents normalisés, erreurs. `None` sans document traité, et la ligne affiche « rien à faire »."""
    parts = []
    if stats.processed:
        parts.append(quantity(stats.processed, "document normalisé", "documents normalisés"))
    if stats.errors:
        parts.append(quantity(stats.errors, "erreur"))
    return ", ".join(parts) or None


type NormalizerFactory = Callable[[Connection, logging.Logger], SourceNormalizer]


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
    """Renvoie le constructeur du normaliseur de chaque source, sur les stores de la phase."""

    raw_store = get_raw_store() if archive else NullRawStore()

    def builder(adapter: SourceAdapter) -> NormalizerFactory:
        def build(conn: Connection, logger: logging.Logger) -> SourceNormalizer:
            return adapter.normalizer()(
                conn,
                logger,
                StagingStore(conn, raw_store),
                SourceRecordStore(conn),
                contribution_store=SourceContributionStore(conn),
                location_store=LocationStore(conn),
                embargo_store=EmbargoStore(conn),
                subject_store=SourceRecordSubjectStore(conn),
            )

        return build

    return {source.value: builder(adapter) for source, adapter in ADAPTERS.items()}


def _run_normalize(ctx: PhaseContext, build: NormalizerFactory) -> NormalizeStats:
    with ctx.open_tx() as conn:
        return build(conn, ctx.logger).run()


TASKS = (
    *(
        task(
            f"normalize.{source}",
            reads=(
                "staging",
                "staging_normalization_queue",
                "source_records.id",
                "source_records.authors_hash",
                "source_records.publication_id",
                "source_contributions.id",
                "source_contributions.author_position",
                "source_contributions.roles",
                "source_contributions.contributor_information_id",
                "source_contributions.content_hash",
                "contributor_information",
                "addresses.id",
                "countries",
                "subjects",
                # Contributions des contributions sources à rôles ou statut de correspondant modifiés.
                "aligned_source_contributions",
            ),
            writes=(
                "staging_normalization_queue",
                "staging.raw_data",
                "source_records",
                "source_record_identifiers",
                "source_record_locations",
                "embargoes",
                "subjects",
                "source_record_subjects",
                "platforms",
                "source_contributions",
                "source_contribution_addresses",
                "source_contribution_rors",
                "source_contribution_hal_structures",
                "contributor_information",
                "addresses.id",
                "address_candidates_queue",
                "address_country_candidates",
                "publication_contributions_queue",
                "source_contribution_countries_queue",
                "source_record_keys_queue",
                "contribution_attributes_queue",
            ),
            # Ses propres lignes de `staging`, de la file de normalisation, enregistrements sources et contributions sources ; les contributions écrites par `author_grouping`.
            previous_run=(
                "staging",
                "staging_normalization_queue",
                "source_records",
                "source_record_locations",
                "embargoes",
                "subjects",
                "source_record_subjects",
                "platforms",
                "source_contributions",
                "contributor_information",
                "addresses",
                "aligned_source_contributions",
            ),
            run=_normalize(source),
            label=source_label(source),
            progress_bar=True,
            when=lambda ctx, source=source: source in ctx.options.sources,
        )
        for source in SOURCE_PRIORITY
    ),
    task(
        "normalize.prune_disappeared",
        reads=(
            "staging.disappeared_at",
            "source_records.id",
            "source_records.staging_id",
            "source_records.publication_id",
        ),
        # La suppression d'un enregistrement source emporte ses localisations, ses contributions sources, leurs adresses, ROR et structures HAL, et les décisions qui les visent.
        writes=(
            "source_records.id",
            "source_record_identifiers",
            "source_record_locations",
            "embargoes",
            "source_record_subjects",
            "source_record_keys_queue",
            "publication_contributions_queue",
            "source_contributions.id",
            "source_contribution_addresses",
            "source_contribution_rors",
            "source_contribution_hal_structures",
            "confirmed_source_contributions",
            "rejected_contributions",
        ),
        previous_run=("source_records",),
        run=_prune,
    ),
    task(
        "normalize.cleanup_orphan_contributor_information",
        reads=("source_contributions.contributor_information_id", "contributor_information.id"),
        writes=("contributor_information.id",),
        previous_run=("source_contributions",),
        run=_cleanup_contributor_information,
        section="Maintenance des tables",
        label="Informations du contributeur orphelines",
    ),
    task(
        "normalize.cleanup_orphan_addresses",
        reads=("source_contribution_addresses", "addresses.id"),
        # La suppression d'une adresse emporte ses liens aux structures.
        writes=("addresses.id", "address_structures"),
        # La normalisation vide `staging.raw_data`. `VACUUM FULL` en mode full.
        maintenance=("VACUUM staging",),
        run=_cleanup_addresses,
        section="Maintenance des tables",
        label="Adresses orphelines",
    ),
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie les métriques de la phase : documents normalisés, table des sources, enregistrements sources disparus supprimés."""
    rows = [
        {**cast("dict[str, object]", metrics.details["row"]), "duration_s": metrics.duration_s}
        for metrics in by_task.values()
        if "row" in metrics.details
    ]
    metrics = PhaseMetrics()
    metrics.add(seen=sum(cast("int", row["processed"]) for row in rows))
    metrics.details["table"] = {"rows": rows}
    metrics.details["disappeared_pruned"] = by_task["normalize.prune_disappeared"].extras.get(
        "disappeared", 0
    )
    return metrics
