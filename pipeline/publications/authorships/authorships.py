"""Phase `authorships` : construction de la table `authorships`.

Quatre sous-étapes :

1. **build_authorships** — consolide les `source_authorships` en authorships canoniques (une entrée par couple publication × personne), avec `in_perimeter` consolidé.
2. **purge des orphelines** — supprime les publications rétrogradées à zéro authorship (défense en profondeur).
3. **référentiels vides** — supprime les monographies, revues et éditeurs que plus rien ne référence, dans cet ordre : une monographie maintient sa collection, une revue ou un préfixe DOI son éditeur. Elle suit les dernières suppressions de publications, donc un référentiel vidé dans le run est supprimé dans le même run.
4. **refresh des `pub_count`** — recalcule le nombre de publications que porte chaque adresse, revue et éditeur.

Le build est incrémental et convergent (add + prune + recompute en une passe) ; le recalcul complet de la table est possible via `run_pipeline --rebuild-authorships`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from pipeline.publications.authorships.address_pub_count import AddressPubCountQueries
from pipeline.publications.authorships.authorships_queries import AuthorshipsBuild
from pipeline.publications.authorships.build_authorships import build as build_authorships
from pipeline.publications.reconciliation.purge_orphan_publications import (
    PurgeOrphanPublicationsQueries,
)
from pipeline.publishing.pub_counts import PgPubCountsQueries
from pipeline.runtime.context import OpenTransaction, Phase, PhaseContext
from pipeline.runtime.execution import log, open_tx
from pipeline.runtime.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape, forme
from pipeline.runtime.metrics import PhaseMetrics
from pipeline.runtime.progression import attente

_PURGE_BATCH_SIZE = 5000


@dataclass(frozen=True)
class AuthorshipsPhase:
    build_queries: AuthorshipsBuild
    purge_queries: PurgeOrphanPublicationsQueries
    pub_counts_queries: PgPubCountsQueries
    address_pub_count_queries: AddressPubCountQueries
    # Suppressions des référentiels vides, dans l'ordre : (libellé, runner). Le câblage les fournit.
    empty_containers: tuple[tuple[str, Callable[[], PhaseMetrics]], ...] = ()

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Enchaîne build → purge → référentiels vides → recalcul des décomptes et retourne les métriques du build."""
        open_tx, logger = ctx.open_tx, ctx.logger
        with open_tx() as conn:
            metrics = build_authorships(
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
    pub_counts_queries: PgPubCountsQueries,
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


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    """Construction du référentiel `authorships`.

    Les signatures des sources se consolident en une entrée par couple publication-personne, avec son appartenance au périmètre ; les structures dérivent de la matview `authorship_structures`. Après les dernières suppressions de publications, les monographies, revues et éditeurs vides sont supprimés.

    La phase reconsolide toutes les sources à chaque run et ignore `--sources` : une signature se trouve modifiée par d'autres voies que sa propre normalisation, comme la repopulation des affiliations ou le recalcul des métadonnées d'une publication.

    Une passe unique ajoute les liens attestés, retire les liens sans attestation et recalcule les attributs, de sorte que la table converge sans être vidée. `run_pipeline --rebuild-authorships` la purge et la reconstruit depuis zéro, en récupération.
    """
    from pipeline.publications.authorships.address_pub_count import AddressPubCountQueries
    from pipeline.publications.authorships.authorships_queries import AuthorshipsBuild
    from pipeline.publications.reconciliation.purge_orphan_publications import (
        PurgeOrphanPublicationsQueries,
    )
    from pipeline.publishing.journals import delete_empty_journals
    from pipeline.publishing.monographs import delete_empty_monographs
    from pipeline.publishing.publishers import delete_empty_publishers

    return AuthorshipsPhase(
        AuthorshipsBuild(),
        PurgeOrphanPublicationsQueries(),
        PgPubCountsQueries(),
        AddressPubCountQueries(),
        empty_containers=(
            (delete_empty_monographs.LIBELLE, _run_delete_empty_monographs),
            (delete_empty_journals.LIBELLE, _run_delete_empty_journals),
            (delete_empty_publishers.LIBELLE, _run_delete_empty_publishers),
        ),
    )


def _run_delete_empty_monographs() -> PhaseMetrics:
    from pipeline.publishing.monographs.delete_empty_monographs import (
        run_delete_empty_monographs,
    )
    from pipeline.publishing.monographs.monographs import MonographGatewayQueries

    with open_tx() as conn:
        return run_delete_empty_monographs(log, monograph_repo=MonographGatewayQueries(conn))


def _run_delete_empty_journals() -> PhaseMetrics:
    from pipeline.publishing.journals.delete_empty_journals import (
        run_delete_empty_journals,
    )
    from pipeline.publishing.journals.journals import JournalGatewayQueries

    with open_tx() as conn:
        return run_delete_empty_journals(log, journal_repo=JournalGatewayQueries(conn))


def _run_delete_empty_publishers() -> PhaseMetrics:
    from pipeline.publishing.publishers.delete_empty_publishers import (
        run_delete_empty_publishers,
    )
    from pipeline.publishing.publishers.publishers import PublisherGatewayQueries

    with open_tx() as conn:
        return run_delete_empty_publishers(log, publisher_repo=PublisherGatewayQueries(conn))
