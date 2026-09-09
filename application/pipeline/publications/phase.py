"""Orchestrateur de la phase `publications` : assignation des `source_publications` aux publications, en une seule passe.

`reconcile_components` clusterise le voisinage des SP dirty par composante connexe des clés de confirmation (DOI/NNT/hal_id/PMID + token thèse `title+year`) et assigne chaque SP au pub-ancre de sa partition `(composante ∩ DOI)`. Assignation (match/create/skip d'un orphelin) et réconciliation (merge/split de publications matérialisées) sont des facettes du même primitif.

`--rebuild-publications` re-dirtie tout le stock avant la réconciliation : celle-ci dégénère alors en cluster-then-materialize global (après une évolution des règles de clés).

Les deux étapes — redirty optionnel, réconciliation — sont indépendantes et idempotentes ; chacune tourne dans sa propre transaction.
"""

import logging
from collections.abc import Callable

from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.pipeline.publications.reconcile_components import run as reconcile_run
from application.ports.pipeline.publications.reconciliation import (
    PublicationsReconciliationQueries,
)
from application.ports.pipeline.transaction import OpenTransaction
from application.ports.repositories.publication_repository import PublicationRepository


def run(
    open_tx: OpenTransaction,
    reconciliation_queries: PublicationsReconciliationQueries,
    logger: logging.Logger,
    *,
    publication_repo_factory: Callable[[Connection], PublicationRepository],
    rebuild_publications: bool = False,
) -> PhaseMetrics:
    """Redirty optionnel, puis réconciliation."""
    if rebuild_publications:
        _redirty_all(open_tx, reconciliation_queries, logger)
    metrics = _reconcile(open_tx, reconciliation_queries, logger, publication_repo_factory)
    metrics.resume = ""
    return metrics


def _redirty_all(
    open_tx: OpenTransaction,
    reconciliation_queries: PublicationsReconciliationQueries,
    logger: logging.Logger,
) -> None:
    with open_tx() as conn:
        n = reconciliation_queries.mark_keys_dirty(conn)
    logger.info("✓ %d source_publications marquées keys_dirty (rebuild complet)", n)


def _reconcile(
    open_tx: OpenTransaction,
    reconciliation_queries: PublicationsReconciliationQueries,
    logger: logging.Logger,
    publication_repo_factory: Callable[[Connection], PublicationRepository],
) -> PhaseMetrics:
    with open_tx() as conn:
        stats = reconcile_run(
            conn,
            reconciliation_queries,
            logger,
            publication_repo=publication_repo_factory(conn),
        )
        pub_total = reconciliation_queries.count_publications(conn)

    metrics = PhaseMetrics()
    metrics.add(total=stats.processed if stats else 0, new=stats.created if stats else 0)
    # Chiffres du run (SP dirty examinées → publications d'arrivée, mouvements) + le total global des publications (`pub_total`) en « nouveau total ». Le frontend les compose en lignes de texte ; les volumes avant/après auto sont masqués.
    metrics.details["summary"] = {
        "processed": stats.processed if stats else 0,
        "publications": stats.publications if stats else 0,
        "existing": stats.existing if stats else 0,
        "created": stats.created if stats else 0,
        "splits": stats.splits if stats else 0,
        "merges": stats.merges if stats else 0,
        "pub_total": pub_total,
    }
    return metrics
