"""Phase `publications` : rattachement des enregistrements sources aux publications (`reconciliation`), idempotent.

Les enregistrements sources modifiés et leurs voisins se regroupent par leurs clés de confirmation (`domain.source_records.keys`), corrigées par la phase `metadata_correction`. Rattacher un enregistrement source, fusionner deux publications ou en scinder une relèvent de la même décision.

`--rebuild-publications` marque tout le stock : la réconciliation applique alors une évolution des règles de clés à toutes les publications.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import Connection, text

from pipeline.runtime.context import OpenTransaction, Phase, PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import TaskStep, run_tasks
from pipeline.transformation.publications.reconciliation import reconcile


def count_publications(conn: Connection) -> int:
    """Compte les publications, toutes dans le périmètre : la réconciliation crée une publication seulement pour une partition du périmètre."""
    return int(conn.execute(text("SELECT count(*) FROM publications")).scalar_one())


@dataclass(frozen=True)
class PublicationsPhase:
    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Réconcilie les enregistrements sources avec les publications, puis ajoute le total des publications aux métriques."""

        def reconcile_task(ctx: PhaseContext) -> PhaseMetrics:
            return _reconcile(ctx.open_tx, ctx.logger, rebuild=ctx.options.rebuild_publications)

        by_task = run_tasks(
            "publications",
            {
                "publications.reconcile": TaskStep(reconcile_task),
            },
            ctx,
        )
        metrics = by_task["publications.reconcile"]
        with ctx.open_tx() as conn:
            publication_total = count_publications(conn)
        summary = metrics.details["summary"]
        if isinstance(summary, dict):
            summary["publication_total"] = publication_total
        return metrics


def _reconcile(open_tx: OpenTransaction, logger: logging.Logger, *, rebuild: bool) -> PhaseMetrics:
    with open_tx() as conn:
        stats = reconcile(conn, logger, rebuild=rebuild)

    metrics = PhaseMetrics()
    metrics.add(seen=stats.processed, new=stats.created)
    # Chiffres du run. `run` ajoute `publication_total`, compté après la suppression des publications sans enregistrement source.
    metrics.details["summary"] = {
        "processed": stats.processed,
        "publications": stats.publications,
        "existing": stats.existing,
        "created": stats.created,
        "splits": stats.splits,
        "merges": stats.merges,
        "detached": stats.detached,
    }
    return metrics


def build() -> Phase:
    return PublicationsPhase()
