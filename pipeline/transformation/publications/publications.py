"""Phase `publications` : rattachement des enregistrements sources aux publications (`reconciliation`), idempotent.

Les enregistrements sources modifiés et leurs voisins se regroupent par leurs clés de confirmation (`domain.source_records.keys`), corrigées par la phase `metadata_correction`. Rattacher un enregistrement source, fusionner deux publications ou en scinder une relèvent de la même décision.

`--rebuild-publications` marque tout le stock : la réconciliation applique alors une évolution des règles de clés à toutes les publications.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from pipeline.graph import Task
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publications.reconciliation import reconcile


def count_publications(conn: Connection) -> int:
    """Compte les publications, toutes dans le périmètre : la réconciliation crée une publication seulement pour une partition du périmètre."""
    return int(conn.execute(text("SELECT count(*) FROM publications")).scalar_one())


def _reconcile(ctx: PhaseContext) -> PhaseMetrics:
    """Réconcilie les enregistrements sources avec les publications, puis compte les publications."""
    with ctx.open_tx() as conn:
        stats = reconcile(conn, ctx.logger, rebuild=ctx.options.rebuild_publications)
        publication_total = count_publications(conn)

    metrics = PhaseMetrics()
    metrics.add(seen=stats.processed, new=stats.created)
    metrics.details["summary"] = {
        "processed": stats.processed,
        "publications": stats.publications,
        "existing": stats.existing,
        "created": stats.created,
        "splits": stats.splits,
        "merges": stats.merges,
        "detached": stats.detached,
        "publication_total": publication_total,
    }
    return metrics


TASKS = (
    Task(
        "publications.reconcile",
        reads=(
            "source_records",
            "source_record_identifiers",
            "doi_targets",
            "source_record_keys_queue",
            "source_contributions.in_perimeter",
            "manual_merge_source_records",
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
        ),
        writes=(
            "publications",
            "publications_detail",
            "source_records.publication_id",
            "source_record_keys_queue",
            "apc_payments.publication_id",
            "publication_contributions_queue",
        ),
        # Réponses d'Unpaywall et de doi.org ; publications supprimées par `finalize.purge_publications` ; revues et monographies vides supprimées par `finalize.delete_empty_containers`.
        previous_run=(
            "source_records.countries",
            "publications.id",
            "publications.oa_status",
            "dois.unpaywall_oa_status",
            "dois.registered_url",
            "serials",
            "monographs",
        ),
        run=_reconcile,
    ),
)
