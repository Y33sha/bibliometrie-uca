"""Orchestrateur de la phase `authorships` : construction de la table `authorships`.

Trois sous-étapes :

1. **build_authorships** — consolide les `source_authorships` en authorships canoniques (une entrée par couple publication × personne), avec `in_perimeter` consolidé.
2. **purge des orphelines** — supprime les publications restées à zéro authorship, puis récupère l'espace churné (maintenance physique, hors transaction).
3. **refresh des `pub_count`** — recalcule les compteurs `journals` + `publishers` qui dérivent de `in_perimeter`.

Le build est incrémental et convergent (add + prune + recompute en une passe) ; le recalcul complet de la table est possible via `run_pipeline --rebuild-authorships`.
"""

import logging
import time

from application.pipeline.authorships.build_authorships import build
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.authorships_build import AuthorshipsBuildQueries
from application.ports.pipeline.pub_counts import PubCountsQueries
from application.ports.pipeline.purge_orphan_publications import PurgeOrphanPublicationsQueries
from application.ports.pipeline.transaction import OpenTransaction

# Taille des lots du DELETE de purge (un commit par lot).
_PURGE_BATCH_SIZE = 5000


def run(
    open_tx: OpenTransaction,
    build_queries: AuthorshipsBuildQueries,
    purge_queries: PurgeOrphanPublicationsQueries,
    pub_counts_queries: PubCountsQueries,
    logger: logging.Logger,
    *,
    rebuild_authorships: bool = False,
) -> PhaseMetrics:
    """Enchaîne build → purge → refresh pub_count et retourne les métriques du build."""
    logger.info("▶ build_authorships")
    t0 = time.perf_counter()
    with open_tx() as conn:
        metrics = build(conn, build_queries, logger, rebuild_full=rebuild_authorships)
    logger.info("✓ build_authorships terminé en %.1fs", time.perf_counter() - t0)

    n_purged = _purge_orphan_publications(open_tx, purge_queries, logger)
    summary = metrics.details["summary"]
    if isinstance(summary, dict):
        summary["publications_purged"] = n_purged
    _refresh_pub_counts(open_tx, pub_counts_queries, logger)
    return metrics


def _purge_orphan_publications(
    open_tx: OpenTransaction, purge_queries: PurgeOrphanPublicationsQueries, logger: logging.Logger
) -> int:
    """Purge par lots (commit par chunk) puis récupération de l'espace churné. Retourne le nombre de publications supprimées."""
    logger.info("▶ purge publications orphelines (zéro authorship)")
    t0 = time.perf_counter()
    n = 0
    with open_tx() as conn:
        while True:
            deleted = purge_queries.purge_orphan_publications(conn, limit=_PURGE_BATCH_SIZE)
            if deleted == 0:
                break
            conn.commit()
            n += deleted
    # Reclaim : maintenance physique hors transaction, encapsulée dans l'adapter.
    purge_queries.vacuum_analyze_churned()
    logger.info(
        "✓ purge : %d publication(s) supprimée(s) + VACUUM ANALYZE en %.1fs",
        n,
        time.perf_counter() - t0,
    )
    return n


def _refresh_pub_counts(
    open_tx: OpenTransaction, pub_counts_queries: PubCountsQueries, logger: logging.Logger
) -> None:
    logger.info("▶ refresh pub_count (journals + publishers)")
    t0 = time.perf_counter()
    with open_tx() as conn:
        changes = pub_counts_queries.refresh_pub_counts(conn)
    logger.info(
        "✓ pub_count : %d revues, %d éditeurs mis à jour en %.1fs",
        changes.journals,
        changes.publishers,
        time.perf_counter() - t0,
    )
