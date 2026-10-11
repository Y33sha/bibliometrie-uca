"""Orchestrateur de la phase `authorships` : construction de la table `authorships`.

Quatre sous-étapes :

1. **build_authorships** — consolide les `source_authorships` en authorships canoniques (une entrée par couple publication × personne), avec `in_perimeter` consolidé.
2. **purge des orphelines** — supprime les publications rétrogradées à zéro authorship (défense en profondeur).
3. **référentiels vides** — supprime les monographies, revues et éditeurs que plus rien ne référence, dans cet ordre : une monographie maintient sa collection, une revue ou un préfixe DOI son éditeur. Elle suit les dernières suppressions de publications, donc un référentiel vidé dans le run est supprimé dans le même run.
4. **refresh des `pub_count`** — recalcule le nombre de publications que porte chaque adresse, revue et éditeur.

Le build est incrémental et convergent (add + prune + recompute en une passe) ; le recalcul complet de la table est possible via `run_pipeline --rebuild-authorships`.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from application.pipeline.authorships.build_authorships import build
from application.pipeline.context import PhaseContext
from application.pipeline.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape, forme
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.progression import attente
from application.ports.pipeline.authorships.address_pub_count import AddressPubCountQueries
from application.ports.pipeline.authorships.build import AuthorshipsBuildQueries
from application.ports.pipeline.authorships.pub_counts import PubCountsQueries
from application.ports.pipeline.authorships.purge_orphan_publications import (
    PurgeOrphanPublicationsQueries,
)
from application.ports.pipeline.transaction import OpenTransaction

# Taille des lots du DELETE de purge (un commit par lot).
_PURGE_BATCH_SIZE = 5000


@dataclass(frozen=True)
class AuthorshipsPhase:
    build_queries: AuthorshipsBuildQueries
    purge_queries: PurgeOrphanPublicationsQueries
    pub_counts_queries: PubCountsQueries
    address_pub_count_queries: AddressPubCountQueries
    # Suppressions des référentiels vides, dans l'ordre : (libellé, runner). Le câblage les fournit.
    empty_containers: tuple[tuple[str, Callable[[], PhaseMetrics]], ...] = ()

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Enchaîne build → purge → référentiels vides → recalcul des décomptes et retourne les métriques du build."""
        open_tx, logger = ctx.open_tx, ctx.logger
        with open_tx() as conn:
            metrics = build(
                conn,
                self.build_queries,
                logger,
                rebuild_full=ctx.options.rebuild_authorships,
            )

        n_purged = _purge_orphan_publications(open_tx, self.purge_queries, logger)
        summary = metrics.details["summary"]
        if isinstance(summary, dict):
            summary["publications_purged"] = n_purged
        _delete_empty_containers(self.empty_containers, metrics, logger)
        _refresh_pub_counts(
            open_tx, self.pub_counts_queries, self.address_pub_count_queries, logger
        )
        # Les sous-étapes affichées journalisent déjà leur décompte : une ligne de clôture les répéterait.
        # La purge reste muette, son décompte va aux métriques.
        metrics.resume = ""
        return metrics


def _purge_orphan_publications(
    open_tx: OpenTransaction, purge_queries: PurgeOrphanPublicationsQueries, logger: logging.Logger
) -> int:
    """Purge par lots (commit par chunk). Retourne le nombre de publications supprimées."""
    n = 0
    with open_tx() as conn:
        while True:
            deleted = purge_queries.purge_orphan_publications(conn, limit=_PURGE_BATCH_SIZE)
            if deleted == 0:
                break
            conn.commit()
            n += deleted
    return n


def _delete_empty_containers(
    steps: tuple[tuple[str, Callable[[], PhaseMetrics]], ...],
    metrics: PhaseMetrics,
    logger: logging.Logger,
) -> None:
    """Supprime les référentiels vides ; chaque suppression écrit sa ligne et reporte ses compteurs à la phase."""
    if not steps:
        return
    etape(logger, "Référentiels vides")
    for indice, (libelle, run) in enumerate(steps):
        sub = run()
        metrics.merge(sub)
        branche = DERNIERE_BRANCHE if indice == len(steps) - 1 else BRANCHE
        logger.info("%s%s : %s", branche, libelle, sub.resume or "rien à faire")


def _refresh_pub_counts(
    open_tx: OpenTransaction,
    pub_counts_queries: PubCountsQueries,
    address_pub_count_queries: AddressPubCountQueries,
    logger: logging.Logger,
) -> None:
    """Recalcule le nombre de publications que porte chaque adresse, revue et éditeur.

    Les trois se lisent des mêmes publications et signatures, stabilisées à ce point du pipeline. Le décompte des éditeurs somme celui des revues, donc le suit.

    Chaque décompte dure : sa ligne annonce le travail en cours, puis cède la place à son résultat.
    """
    etape(logger, "Recalcul des décomptes de publications")

    with attente(f"{BRANCHE}par adresse", logger) as ligne:
        with open_tx() as conn:
            adresses = address_pub_count_queries.recompute_pub_count(conn)
        ligne.conclut(
            f"{BRANCHE}{accord(adresses, 'adresse')} {forme(adresses, 'mise à jour', 'mises à jour')}"
        )

    with attente(f"{BRANCHE}par revue", logger) as ligne:
        with open_tx() as conn:
            revues = pub_counts_queries.refresh_journal_pub_counts(conn)
        ligne.conclut(
            f"{BRANCHE}{accord(revues, 'revue')} {forme(revues, 'mise à jour', 'mises à jour')}"
        )

    with attente(f"{DERNIERE_BRANCHE}par éditeur", logger) as ligne:
        with open_tx() as conn:
            editeurs = pub_counts_queries.refresh_publisher_pub_counts(conn)
        # « mis à jour » ne varie pas au pluriel, contrairement à « mise à jour ».
        ligne.conclut(f"{DERNIERE_BRANCHE}{accord(editeurs, 'éditeur')} mis à jour")
