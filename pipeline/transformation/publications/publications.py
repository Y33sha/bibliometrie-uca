"""Phase `publications` : rattachement des enregistrements sources aux publications (`reconciliation`), idempotent, puis recalcul des publications de la file de consolidation.

Les enregistrements sources modifiés et leurs voisins se regroupent par leurs clés de confirmation (`domain.source_records.keys`), corrigées par la phase `metadata_correction`. Rattacher un enregistrement source, fusionner deux publications ou en scinder une relèvent de la même décision. La réconciliation recalcule les publications touchées. La file `publications_queue` contient les autres publications à recalculer : un enregistrement source a changé de pays.

`--rebuild-publications` marque tout le stock : la réconciliation applique alors une évolution des règles de clés à toutes les publications.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from pipeline.graph import Task
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publications import lifecycle
from pipeline.transformation.publications.reconciliation import reconcile


def count_publications(conn: Connection) -> int:
    """Compte les publications."""
    return int(conn.execute(text("SELECT count(*) FROM publications")).scalar_one())


def _reconcile(ctx: PhaseContext) -> PhaseMetrics:
    """Réconcilie les enregistrements sources avec les publications, puis compte les publications."""
    with ctx.open_tx() as conn:
        stats = reconcile(conn, ctx.logger, rebuild=ctx.options.rebuild_publications)
        publication_total = count_publications(conn)

    metrics = PhaseMetrics()
    metrics.add(seen=stats.processed, new=stats.created)
    metrics.details["summary"] = {**stats._asdict(), "publication_total": publication_total}
    return metrics


def _consolidate(ctx: PhaseContext) -> PhaseMetrics:
    """Recalcule les publications de la file de consolidation."""
    with ctx.open_tx() as conn:
        refreshed = lifecycle.refresh_queued(conn)
    metrics = PhaseMetrics()
    metrics.add(seen=refreshed)
    metrics.report = quantity(refreshed, "publication recalculée", "publications recalculées")
    return metrics


_CONSOLIDATION_READS = (
    "source_records",
    "source_record_identifiers",
    "doi_targets",
    # Copies des enregistrements sources : la publication retient la meilleure.
    "source_record_locations",
    "platforms.name",
    "platforms.openalex_id",
    "platforms.platform_type",
    "embargoes",
    "dois.registered_url",
    "publications",
    "apc_payments",
    "serials.serial_type",
    "serials.oa_model",
    "monographs.serial_id",
    "dois.unpaywall_oa_status",
    # Titulaire du préfixe DOI Crossref, éditeur de la publication.
    "doi_prefixes.ra",
    "doi_prefixes.publisher_id",
)
"""Lectures de la consolidation des publications (`lifecycle.refresh`)."""

_CONSOLIDATION_WRITES = (
    "publications",
    "contributions.id",
    "aligned_source_contributions",
    "contribution_resolution_queue",
    "publication_relations",
    "publication_subjects",
    "publications_detail",
    "apc_payments.publication_id",
)
"""Écritures de la consolidation des publications. La suppression d'une publication emporte ses contributions, leurs alignements, ses relations, ses sujets et son détail. Elle détache ses paiements APC."""

_CONSOLIDATION_PREVIOUS_RUN = (
    "publications.id",
    "source_records.publication_id",
    "apc_payments.publication_id",
    "publications.oa_status",
    "dois.unpaywall_oa_status",
    "dois.registered_url",
    "serials",
    "monographs",
)
"""Lectures du run précédent de la consolidation : réponses d'Unpaywall et de doi.org ; publications supprimées, enregistrements sources et paiements APC détachés par `finalize.purge_publications` ; revues et monographies vides supprimées par `finalize`."""

TASKS = (
    Task(
        "reconcile",
        reads=(
            *_CONSOLIDATION_READS,
            "source_record_keys_queue",
            "source_contributions.in_perimeter",
            "manual_merge_source_records",
        ),
        writes=(
            *_CONSOLIDATION_WRITES,
            "source_records.publication_id",
            # DOI d'une autre partition, retirés par la réconciliation.
            "source_record_identifiers.removed_by",
            "source_record_keys_queue",
            "publication_contributions_queue",
        ),
        previous_run=_CONSOLIDATION_PREVIOUS_RUN,
        run=_reconcile,
    ),
    Task(
        "consolidate",
        reads=(*_CONSOLIDATION_READS, "publications_queue"),
        writes=(*_CONSOLIDATION_WRITES, "publications_queue"),
        previous_run=_CONSOLIDATION_PREVIOUS_RUN,
        run=_consolidate,
        section="Recalcul des publications dont un enregistrement source a changé de pays",
        label="Publications en file",
        silent_when_empty=True,
    ),
)
