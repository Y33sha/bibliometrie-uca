"""Phase `publications` : assignation des `source_publications` aux publications, en une seule passe.

`reconcile_components` clusterise le voisinage des SP dirty par composante connexe des clés de confirmation (DOI/NNT/hal_id/PMID + token thèse `title+year`) et assigne chaque SP au pub-ancre de sa partition `(composante ∩ DOI)`. Assignation (match/create/skip d'un orphelin) et réconciliation (merge/split de publications matérialisées) sont des facettes du même primitif.

`--rebuild-publications` re-dirtie tout le stock au début de la réconciliation : celle-ci dégénère alors en cluster-then-materialize global (après une évolution des règles de clés).

La réconciliation est suivie de la suppression des publications restées sans source : celles que la réconciliation a vidées, et celles dont la phase `normalize` a retiré les derniers documents disparus.

Les deux nœuds (`pipeline.graph`) — réconciliation, suppression — sont idempotents ; chacun tourne dans sa propre transaction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pipeline.node_runner import NodeStep, run_nodes
from pipeline.runtime.context import OpenTransaction, Phase, PhaseContext
from pipeline.runtime.observability.libelles import DERNIERE_BRANCHE, accord, etape, forme
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publications.lifecycle import delete_publications_without_sources
from pipeline.transformation.publications.reconciliation.reconcile_components import (
    run as reconcile_run,
)
from pipeline.transformation.publications.reconciliation.reconciliation import (
    PublicationsReconciliationQueries,
)


@dataclass(frozen=True)
class PublicationsPhase:
    reconciliation_queries: PublicationsReconciliationQueries

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Réconciliation, puis suppression des publications restées sans source."""
        reconciliation_queries = self.reconciliation_queries

        def reconcile(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            return _reconcile(
                ctx.open_tx,
                reconciliation_queries,
                ctx.logger,
                rebuild=ctx.options.rebuild_publications,
            )

        def delete_without_sources(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            _delete_publications_without_sources(ctx.open_tx, ctx.logger)
            return PhaseMetrics()

        by_node = run_nodes(
            "publications",
            {
                "publications.reconcile": NodeStep(reconcile),
                "publications.delete_without_sources": NodeStep(delete_without_sources),
            },
            ctx,
        )
        metrics = by_node["publications.reconcile"]
        with ctx.open_tx() as conn:
            pub_total = reconciliation_queries.count_publications(conn)
        summary = metrics.details["summary"]
        if isinstance(summary, dict):
            summary["pub_total"] = pub_total
        metrics.resume = ""
        return metrics


def _delete_publications_without_sources(open_tx: OpenTransaction, logger: logging.Logger) -> int:
    """Supprime les publications restées sans source. Retourne leur nombre."""
    with open_tx() as conn:
        n = delete_publications_without_sources(conn)
    if n:
        etape(logger, "Publications sans source")
        logger.info("%s%s %s", DERNIERE_BRANCHE, accord(n, "publication"), forme(n, "supprimée"))
    return n


def _reconcile(
    open_tx: OpenTransaction,
    reconciliation_queries: PublicationsReconciliationQueries,
    logger: logging.Logger,
    *,
    rebuild: bool,
) -> PhaseMetrics:
    with open_tx() as conn:
        stats = reconcile_run(
            conn,
            reconciliation_queries,
            logger,
            rebuild=rebuild,
        )

    metrics = PhaseMetrics()
    metrics.add(seen=stats.processed if stats else 0, new=stats.created if stats else 0)
    # Chiffres du run ; `run` y ajoute `pub_total`, compté après la suppression des publications sans source.
    metrics.details["summary"] = {
        "processed": stats.processed if stats else 0,
        "publications": stats.publications if stats else 0,
        "existing": stats.existing if stats else 0,
        "created": stats.created if stats else 0,
        "splits": stats.splits if stats else 0,
        "merges": stats.merges if stats else 0,
        "detached": stats.detached if stats else 0,
    }
    return metrics


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    """Assignation des `source_publications` aux publications, en une seule passe.

    Les documents sources modifiés et leur voisinage sont regroupés par composante connexe de leurs clés de confirmation — DOI, NNT, hal_id, PMID, et pour les thèses le couple titre-année. Chaque document rejoint la publication qui ancre sa partition. Rattacher un document, fusionner deux publications ou en scinder une sont trois lectures du même regroupement.

    La phase suit `metadata_correction`, qui a substitué le DOI de concept aux DOI de version DataCite : le regroupement se fait alors sur le concept.

    `--rebuild-publications` marque tout le stock à traiter avant le regroupement, qui reprend alors le corpus entier. Sert après une évolution des règles de clés, pour matérialiser les fusions et scissions qu'elles impliquent.
    """
    from pipeline.transformation.publications.reconciliation.reconciliation import (
        PublicationsReconciliationQueries,
    )

    return PublicationsPhase(PublicationsReconciliationQueries())
