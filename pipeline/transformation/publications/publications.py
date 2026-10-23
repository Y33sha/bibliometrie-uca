"""Phase `publications` : assignation des `source_records` aux publications, en une seule passe.

Les documents sources modifiés et leur voisinage sont regroupés par composante connexe de leurs clés de confirmation — DOI, NNT, hal_id, PMID, et pour les thèses le couple titre-année (`reconciliation`). Chaque document rejoint la publication qui ancre sa partition. Rattacher un document, fusionner deux publications ou en scinder une sont trois lectures du même regroupement.

La phase suit `metadata_correction`, qui a substitué le DOI de concept aux DOI de version DataCite : le regroupement se fait alors sur le concept.

`--rebuild-publications` marque tout le stock à traiter avant le regroupement, qui reprend alors le corpus entier. Sert après une évolution des règles de clés, pour matérialiser les fusions et scissions qu'elles impliquent.

La réconciliation est suivie de la suppression des publications restées sans source : celles que la réconciliation a vidées, et celles dont la phase `normalize` a retiré les derniers documents disparus.

Les deux tâches (`pipeline.graph`) — réconciliation, suppression — sont idempotentes ; chacune tourne dans sa propre transaction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import Connection, text

from pipeline.runtime.context import OpenTransaction, Phase, PhaseContext
from pipeline.runtime.observability.log_format import LAST_BRANCH, inflect, quantity, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import TaskStep, run_tasks
from pipeline.transformation.publications.lifecycle import delete_publications_without_sources
from pipeline.transformation.publications.reconciliation import reconcile


def count_publications(conn: Connection) -> int:
    """Total des publications, toutes dans le périmètre : la réconciliation crée une publication seulement pour une partition du périmètre."""
    return int(conn.execute(text("SELECT count(*) FROM publications")).scalar_one())


@dataclass(frozen=True)
class PublicationsPhase:
    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Réconciliation, puis suppression des publications restées sans source."""

        def reconcile_task(ctx: PhaseContext) -> PhaseMetrics:
            return _reconcile(ctx.open_tx, ctx.logger, rebuild=ctx.options.rebuild_publications)

        def delete_without_sources(ctx: PhaseContext) -> PhaseMetrics:
            _delete_publications_without_sources(ctx.open_tx, ctx.logger)
            return PhaseMetrics()

        by_task = run_tasks(
            "publications",
            {
                "publications.reconcile": TaskStep(reconcile_task),
                "publications.delete_without_sources": TaskStep(delete_without_sources),
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


def _delete_publications_without_sources(open_tx: OpenTransaction, logger: logging.Logger) -> int:
    """Supprime les publications restées sans source. Retourne leur nombre."""
    with open_tx() as conn:
        n = delete_publications_without_sources(conn)
    if n:
        step(logger, "Publications sans source")
        logger.info("%s%s %s", LAST_BRANCH, quantity(n, "publication"), inflect(n, "supprimée"))
    return n


def _reconcile(open_tx: OpenTransaction, logger: logging.Logger, *, rebuild: bool) -> PhaseMetrics:
    with open_tx() as conn:
        stats = reconcile(conn, logger, rebuild=rebuild)

    metrics = PhaseMetrics()
    metrics.add(seen=stats.processed, new=stats.created)
    # Chiffres du run ; `run` y ajoute `publication_total`, compté après la suppression des publications sans source.
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


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    return PublicationsPhase()
