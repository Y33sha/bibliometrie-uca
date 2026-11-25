"""Phase `normalize` : normalisation de `staging` vers les enregistrements sources, les contributions sources et les adresses.

Les enregistrements sources sont écrits sans publication. La phase `publications` les rattache à une publication.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import cast

from sqlalchemy import Connection

from domain.source_records.inspire_author_lists import WITHHELD_AUTHORS_SOURCE
from domain.sources.registry import SOURCE_PRIORITY, Source, source_label
from infrastructure.raw_store import NullRawStore, get_raw_store
from pipeline.graph import Block, Phase, Step, Task, TaskRun
from pipeline.ingestion.adapters import adapter
from pipeline.ingestion.common.embargoes import EmbargoStore
from pipeline.ingestion.common.inspire_author_lists import withhold_covered_source_contributions
from pipeline.ingestion.common.locations import LocationStore
from pipeline.ingestion.common.normalizer import (
    NormalizeStats,
    SourceNormalizer,
)
from pipeline.ingestion.common.source_contribution_store import (
    SourceContributionStore,
    delete_orphan_addresses,
    delete_orphan_contributor_information,
)
from pipeline.ingestion.common.source_records import (
    SourceRecordStore,
    delete_disappeared_source_records,
)
from pipeline.ingestion.common.staging import StagingStore
from pipeline.ingestion.common.subjects import SourceRecordSubjectStore
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics, ReportNote
from pipeline.transformation.persons.arbitration import ARBITRATE_IDENTIFIERS


def build_normalizer(
    source: str, conn: Connection, logger: logging.Logger, *, archive: bool = True
) -> SourceNormalizer:
    """Renvoie le normaliseur de `source`, sur les stores de la phase. Avec `archive`, il archive les payloads dans le raw store."""
    raw_store = get_raw_store() if archive else NullRawStore()
    return adapter(Source(source)).normalizer(
        conn,
        logger,
        StagingStore(conn, raw_store),
        SourceRecordStore(conn),
        contribution_store=SourceContributionStore(conn),
        location_store=LocationStore(conn),
        embargo_store=EmbargoStore(conn),
        subject_store=SourceRecordSubjectStore(conn),
    )


def _normalize(source: str) -> TaskRun:
    """Renvoie l'exécution de la normalisation de `source`, avec sa ligne de la table d'observabilité."""

    def run(ctx: PhaseContext) -> PhaseMetrics:
        with ctx.open_tx() as conn:
            normalizer = build_normalizer(source, conn, ctx.logger, archive=ctx.options.raw_store)
            stats = normalizer.run()
        metrics = PhaseMetrics(report=_report(stats), notes=_notes(stats))
        metrics.details["row"] = {
            "key": source,
            "processed": stats.processed,
            "skipped": stats.skipped,
            "discarded": len(stats.discarded),
            "errors": stats.errors,
        }
        return metrics

    return run


def _report(stats: NormalizeStats) -> str | None:
    """Renvoie la ligne de bilan d'une source : documents normalisés, documents écartés, erreurs. `None` sans document traité."""
    parts = []
    if stats.processed:
        parts.append(quantity(stats.processed, "document normalisé", "documents normalisés"))
    if stats.discarded:
        parts.append(quantity(len(stats.discarded), "document écarté", "documents écartés"))
    if stats.errors:
        parts.append(quantity(stats.errors, "erreur"))
    return ", ".join(parts) or None


def _notes(stats: NormalizeStats) -> list[ReportNote]:
    """Renvoie le récapitulatif d'une source : documents écartés, puis documents par type inconnu."""
    notes = []
    if stats.discarded:
        notes.append(
            ReportNote(
                "documents écartés aux métadonnées incomplètes ou non conformes", stats.discarded
            )
        )
    for raw_type, identifiers in sorted(stats.unknown_doc_types.items()):
        notes.append(
            ReportNote(
                f"{quantity(len(identifiers), 'document')} de type inconnu « {raw_type} »",
                identifiers,
            )
        )
    return notes


def _withhold_authors(ctx: PhaseContext) -> PhaseMetrics:
    """Supprime les contributions sources des enregistrements sources OpenAlex du même document qu'un enregistrement source INSPIRE-HEP."""
    with ctx.open_tx() as conn:
        withheld = withhold_covered_source_contributions(conn, ctx.logger)
    report = None
    if withheld:
        report = (
            quantity(
                withheld,
                "contribution source OpenAlex supprimée",
                "contributions sources OpenAlex supprimées",
            )
            + " (listes d'auteurs d'INSPIRE-HEP)"
        )
    return PhaseMetrics(extras={"withheld": withheld}, report=report)


def _prune(ctx: PhaseContext) -> PhaseMetrics:
    """Supprime les enregistrements sources des documents disparus de leur source."""
    with ctx.open_tx() as conn:
        disappeared = delete_disappeared_source_records(conn)
    report = "aucun document disparu de sa source"
    if disappeared:
        report = (
            quantity(disappeared, "document supprimé", "documents supprimés")
            + " (disparus de leur source)"
        )
    return PhaseMetrics(extras={"disappeared": disappeared}, report=report)


def _cleanup(delete: Callable[[Connection], int], deleted_one: str, deleted_many: str) -> TaskRun:
    """Renvoie l'exécution d'une suppression de lignes orphelines, avec sa ligne de bilan."""

    def run(ctx: PhaseContext) -> PhaseMetrics:
        with ctx.open_tx() as conn:
            deleted = delete(conn)
        metrics = PhaseMetrics()
        if deleted:
            metrics.report = quantity(deleted, deleted_one, deleted_many)
        return metrics

    return run


_BY_SOURCE = tuple(
    Task(
        str(source),
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
            # Identifiants des enregistrements sources INSPIRE-HEP, pour la normalisation d'OpenAlex.
            *(("source_record_identifiers",) if source == WITHHELD_AUTHORS_SOURCE else ()),
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
        previous_runs=(
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
            *(("source_record_identifiers",) if source == WITHHELD_AUTHORS_SOURCE else ()),
        ),
        run=_normalize(source),
        label=source_label(source),
        when=lambda ctx, source=source: source in ctx.options.sources,
    )
    for source in SOURCE_PRIORITY
)


_CHILDREN = (
    Step(
        "by_source",
        "documents bruts de chaque source → enregistrements sources, contributions sources, adresses",
        _BY_SOURCE,
    ),
    Step(
        "removals",
        "enregistrements sources INSPIRE-HEP, documents disparus → contributions sources OpenAlex en double et enregistrements sources disparus supprimés",
        (
            Task(
                "withhold_openalex_authors",
                reads=(
                    "source_records.id",
                    "source_records.source",
                    "source_records.authors_hash",
                    "source_records.publication_id",
                    "source_record_identifiers",
                    "source_contributions.source_record_id",
                ),
                # La suppression d'une contribution source emporte ses adresses, ROR et structures HAL, son alignement et son épinglage.
                writes=(
                    "source_contributions.id",
                    "source_contribution_addresses",
                    "source_contribution_rors",
                    "source_contribution_hal_structures",
                    "aligned_source_contributions",
                    "confirmed_source_contributions",
                    "source_records.authors_hash",
                    "source_records.author_count",
                    "source_records.distinct_author_count",
                    "publication_contributions_queue",
                ),
                previous_runs=(
                    "source_records",
                    "source_record_identifiers",
                    "source_contributions",
                ),
                run=_withhold_authors,
            ),
            Task(
                "prune_disappeared",
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
                previous_runs=("source_records",),
                run=_prune,
            ),
        ),
        section="Contributions sources en double et documents disparus",
    ),
    # La normalisation réassigne des contributions sources, et l'étape `removals` en supprime : des informations du contributeur et des adresses perdent leur dernière contribution source.
    Step(
        "cleanup",
        "contributions sources → informations du contributeur et adresses sans contribution source supprimées",
        (
            Task(
                "cleanup_orphan_contributor_information",
                reads=(
                    "source_contributions.contributor_information_id",
                    "contributor_information.id",
                ),
                writes=("contributor_information.id",),
                previous_runs=("source_contributions",),
                run=_cleanup(
                    delete_orphan_contributor_information, "ligne supprimée", "lignes supprimées"
                ),
                label="Informations du contributeur orphelines",
            ),
            Task(
                "cleanup_orphan_addresses",
                reads=("source_contribution_addresses", "addresses.id"),
                # La suppression d'une adresse emporte ses liens aux structures.
                writes=("addresses.id", "address_structures"),
                # La normalisation vide `staging.raw_data`. `VACUUM FULL` en mode full.
                maintenance=("VACUUM staging",),
                run=_cleanup(delete_orphan_addresses, "adresse supprimée", "adresses supprimées"),
                label="Adresses orphelines",
            ),
        ),
        section="Maintenance des tables",
    ),
    ARBITRATE_IDENTIFIERS,
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie les métriques de la phase : documents normalisés, table des sources, enregistrements sources disparus supprimés, identifiants neutralisés par l'arbitrage."""
    rows = [
        {**cast("dict[str, object]", metrics.details["row"]), "duration_s": metrics.duration_s}
        for metrics in by_task.values()
        if "row" in metrics.details
    ]
    metrics = PhaseMetrics()
    metrics.add(seen=sum(cast("int", row["processed"]) for row in rows))
    metrics.details["table"] = {"rows": rows}
    metrics.details["disappeared_pruned"] = by_task["prune_disappeared"].extras.get(
        "disappeared", 0
    )
    arbitration = by_task[ARBITRATE_IDENTIFIERS.name].extras
    metrics.details["summary"] = {
        "identifiers_neutralized": arbitration.get("neutralized", 0),
        "marked_contributions": arbitration.get("marked_contributions", 0),
    }
    return metrics


PHASE = Phase(
    "normalize",
    "Normalisation des documents bruts",
    _CHILDREN,
    Block.HARVESTING,
    assemble=assemble,
)
