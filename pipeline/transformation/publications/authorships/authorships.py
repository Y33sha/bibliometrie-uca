"""Phase `authorships` : construction de la table `authorships`.

Nœuds (`pipeline.graph`), chacun dans sa transaction :

1. **build** — consolide les `source_authorships` en authorships canoniques (une entrée par couple publication × personne). Sa maintenance `ANALYZE authorships` précède la propagation.
2. **propagate**, **publications_in_perimeter**, **structures** — recomposent les attributs des authorships (indices de l'entrée dans le périmètre compris), le périmètre des publications et les matviews `authorship_structures`, `publication_structures`.
3. **purge des orphelines** — supprime les publications rétrogradées à zéro authorship (défense en profondeur).
4. **référentiels vides** — supprime les monographies, revues et éditeurs que plus rien ne référence, dans cet ordre : une monographie maintient sa collection, une revue ou un préfixe DOI son éditeur. Elle suit les dernières suppressions de publications, donc un référentiel vidé dans le run est supprimé dans le même run.
5. **refresh des `pub_count`** — recalcule le nombre de publications que porte chaque adresse, revue et éditeur.

Le build est incrémental et convergent (add + prune + recompute en une passe).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from pipeline.node_runner import NodeStep, run_nodes
from pipeline.runtime.context import OpenTransaction, Phase, PhaseContext
from pipeline.runtime.observability.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape, forme
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import attente
from pipeline.transformation.publications.authorships.address_pub_count import (
    AddressPubCountQueries,
)
from pipeline.transformation.publications.authorships.authorships_queries import AuthorshipsBuild
from pipeline.transformation.publications.authorships.build_authorships import (
    build as build_authorships,
)
from pipeline.transformation.publications.reconciliation.purge_orphan_publications import (
    PurgeOrphanPublicationsQueries,
)
from pipeline.transformation.publishing.pub_counts import PgPubCountsQueries

_PURGE_BATCH_SIZE = 5000


@dataclass(frozen=True)
class AuthorshipsPhase:
    build_queries: AuthorshipsBuild
    purge_queries: PurgeOrphanPublicationsQueries
    pub_counts_queries: PgPubCountsQueries
    address_pub_count_queries: AddressPubCountQueries
    # Suppressions des référentiels vides, dans l'ordre : (libellé, runner). Le câblage les fournit.
    empty_containers: tuple[tuple[str, Callable[[PhaseContext], PhaseMetrics]], ...] = ()

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute les nœuds de la phase et retourne les métriques du build."""
        queries = self.build_queries

        def build(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                return build_authorships(conn, queries, ctx.logger)

        def propagate(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            t0 = time.perf_counter()
            with ctx.open_tx() as conn:
                queries.propagate_authorship_attributes(conn)
                in_perimeter = queries.count_authorships_in_perimeter(conn)
            metrics = _chronometre(t0)
            metrics.details["in_perimeter"] = in_perimeter
            return metrics

        def publications_in_perimeter(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            t0 = time.perf_counter()
            with ctx.open_tx() as conn:
                queries.refresh_publications_perimeter_evidence(conn)
            return _chronometre(t0)

        def structures(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            t0 = time.perf_counter()
            with ctx.open_tx() as conn:
                queries.refresh_authorship_structures(conn)
                queries.refresh_publication_structures(conn)
            return _chronometre(t0)

        def purge(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            metrics = PhaseMetrics()
            metrics.details["purged"] = _purge_orphan_publications(
                ctx.open_tx, self.purge_queries, ctx.logger
            )
            return metrics

        def empty_containers(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            metrics = PhaseMetrics()
            _delete_empty_containers(self.empty_containers, metrics, ctx)
            return metrics

        def pub_counts(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            _refresh_pub_counts(
                ctx.open_tx, self.pub_counts_queries, self.address_pub_count_queries, ctx.logger
            )
            return PhaseMetrics()

        synchronisation = "Synchronisation des tables"
        by_node = run_nodes(
            "authorships",
            {
                "authorships.build": NodeStep(build),
                "authorships.propagate": NodeStep(
                    propagate, section=synchronisation, label="Attributs des liens"
                ),
                "authorships.publications_in_perimeter": NodeStep(
                    publications_in_perimeter,
                    section=synchronisation,
                    label="Périmètre des publications",
                ),
                "authorships.structures": NodeStep(
                    structures, section=synchronisation, label="Structures des liens"
                ),
                "authorships.purge_orphan_publications": NodeStep(purge),
                "authorships.delete_empty_containers": NodeStep(empty_containers),
                "authorships.pub_counts": NodeStep(pub_counts),
            },
            ctx,
        )
        metrics = by_node["authorships.build"]
        metrics.merge(by_node["authorships.delete_empty_containers"])
        summary = metrics.details["summary"]
        if isinstance(summary, dict):
            summary["total_in_perimeter"] = by_node["authorships.propagate"].details["in_perimeter"]
            summary["publications_purged"] = by_node[
                "authorships.purge_orphan_publications"
            ].details["purged"]
        return metrics


def _chronometre(t0: float) -> PhaseMetrics:
    """Métriques d'un nœud de synchronisation, dont le bilan est sa durée."""
    metrics = PhaseMetrics()
    metrics.report = f"{time.perf_counter() - t0:.1f}s"
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
    steps: tuple[tuple[str, Callable[[PhaseContext], PhaseMetrics]], ...],
    metrics: PhaseMetrics,
    ctx: PhaseContext,
) -> None:
    """Supprime les référentiels vides ; chaque suppression écrit sa ligne et reporte ses compteurs à la phase."""
    if not steps:
        return
    etape(ctx.logger, "Référentiels vides")
    for indice, (libelle, run) in enumerate(steps):
        sub = run(ctx)
        metrics.merge(sub)
        branche = DERNIERE_BRANCHE if indice == len(steps) - 1 else BRANCHE
        ctx.logger.info("%s%s : %s", branche, libelle, sub.report or "rien à faire")


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

    Une passe unique ajoute les liens attestés, retire les liens sans attestation et recalcule les attributs, de sorte que la table converge sans être vidée.
    """
    from pipeline.transformation.publications.authorships.address_pub_count import (
        AddressPubCountQueries,
    )
    from pipeline.transformation.publications.authorships.authorships_queries import (
        AuthorshipsBuild,
    )
    from pipeline.transformation.publications.reconciliation.purge_orphan_publications import (
        PurgeOrphanPublicationsQueries,
    )
    from pipeline.transformation.publishing.journals import delete_empty_journals
    from pipeline.transformation.publishing.monographs import delete_empty_monographs
    from pipeline.transformation.publishing.publishers import delete_empty_publishers

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


def _run_delete_empty_monographs(ctx: PhaseContext) -> PhaseMetrics:
    from pipeline.transformation.publishing.monographs.delete_empty_monographs import (
        run_delete_empty_monographs,
    )
    from pipeline.transformation.publishing.monographs.monographs import MonographGatewayQueries

    with ctx.open_tx() as conn:
        return run_delete_empty_monographs(ctx.logger, monograph_repo=MonographGatewayQueries(conn))


def _run_delete_empty_journals(ctx: PhaseContext) -> PhaseMetrics:
    from pipeline.transformation.publishing.journals.delete_empty_journals import (
        run_delete_empty_journals,
    )
    from pipeline.transformation.publishing.journals.journals import JournalGatewayQueries

    with ctx.open_tx() as conn:
        return run_delete_empty_journals(ctx.logger, journal_repo=JournalGatewayQueries(conn))


def _run_delete_empty_publishers(ctx: PhaseContext) -> PhaseMetrics:
    from pipeline.transformation.publishing.publishers.delete_empty_publishers import (
        run_delete_empty_publishers,
    )
    from pipeline.transformation.publishing.publishers.publishers import PublisherGatewayQueries

    with ctx.open_tx() as conn:
        return run_delete_empty_publishers(ctx.logger, publisher_repo=PublisherGatewayQueries(conn))
