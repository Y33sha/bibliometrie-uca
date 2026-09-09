"""Orchestrateur de la phase `authorships` : construction de la table `authorships`.

Trois sous-étapes :

1. **build_authorships** — consolide les `source_authorships` en authorships canoniques (une entrée par couple publication × personne), avec `in_perimeter` consolidé.
2. **purge des orphelines** — supprime les publications rétrogradées à zéro authorship (défense en profondeur).
3. **refresh des `pub_count`** — recalcule les compteurs `journals` + `publishers` qui dérivent de `in_perimeter`.

Le build est incrémental et convergent (add + prune + recompute en une passe) ; le recalcul complet de la table est possible via `run_pipeline --rebuild-authorships`.
"""

import logging
import time

from application.pipeline.authorships.build_authorships import build
from application.pipeline.libelles import BRANCHE, DERNIERE_BRANCHE, ETAPE, accord
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.authorships.address_pub_count import AddressPubCountQueries
from application.ports.pipeline.authorships.build import AuthorshipsBuildQueries
from application.ports.pipeline.authorships.pub_counts import PubCountsQueries
from application.ports.pipeline.authorships.purge_orphan_publications import (
    PurgeOrphanPublicationsQueries,
)
from application.ports.pipeline.transaction import OpenTransaction

# Taille des lots du DELETE de purge (un commit par lot).
_PURGE_BATCH_SIZE = 5000


def run(
    open_tx: OpenTransaction,
    build_queries: AuthorshipsBuildQueries,
    purge_queries: PurgeOrphanPublicationsQueries,
    pub_counts_queries: PubCountsQueries,
    address_pub_count_queries: AddressPubCountQueries,
    logger: logging.Logger,
    *,
    rebuild_authorships: bool = False,
) -> PhaseMetrics:
    """Enchaîne build → purge → recalcul des décomptes et retourne les métriques du build."""
    with open_tx() as conn:
        metrics = build(conn, build_queries, logger, rebuild_full=rebuild_authorships)

    n_purged = _purge_orphan_publications(open_tx, purge_queries, logger)
    summary = metrics.details["summary"]
    if isinstance(summary, dict):
        summary["publications_purged"] = n_purged
    _refresh_pub_counts(open_tx, pub_counts_queries, address_pub_count_queries, logger)
    return metrics


def _purge_orphan_publications(
    open_tx: OpenTransaction, purge_queries: PurgeOrphanPublicationsQueries, logger: logging.Logger
) -> int:
    """Purge par lots (commit par chunk). Retourne le nombre de publications supprimées."""
    t0 = time.perf_counter()
    n = 0
    with open_tx() as conn:
        while True:
            deleted = purge_queries.purge_orphan_publications(conn, limit=_PURGE_BATCH_SIZE)
            if deleted == 0:
                break
            conn.commit()
            n += deleted
    logger.info(
        "✓ purge : %d publication(s) supprimée(s) en %.1fs",
        n,
        time.perf_counter() - t0,
    )
    return n


def _refresh_pub_counts(
    open_tx: OpenTransaction,
    pub_counts_queries: PubCountsQueries,
    address_pub_count_queries: AddressPubCountQueries,
    logger: logging.Logger,
) -> None:
    """Recalcule le nombre de publications que porte chaque adresse, revue et éditeur.

    Les trois se lisent des mêmes publications et signatures, stabilisées à ce point du pipeline.
    """
    logger.info("")
    logger.info("%sRecalcul des décomptes de publications", ETAPE)
    with open_tx() as conn:
        adresses = address_pub_count_queries.recompute_pub_count(conn)
    logger.info("%s%s", BRANCHE, accord(adresses, "adresse"))

    with open_tx() as conn:
        changes = pub_counts_queries.refresh_pub_counts(conn)
    logger.info("%s%s", BRANCHE, accord(changes.journals, "revue"))
    logger.info("%s%s", DERNIERE_BRANCHE, accord(changes.publishers, "éditeur"))
