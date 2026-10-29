"""Phase `finalize` : données dérivées des contributions, après la résolution des personnes. Chaque tâche a sa transaction.

La phase recompose le périmètre des publications et les vues matérialisées des structures, supprime les publications sans enregistrement source ou sans contribution, recalcule l'éditeur des revues, supprime les référentiels vides, puis recompte les publications des adresses, revues et éditeurs.

Les référentiels vides se suppriment dans l'ordre monographies, revues, éditeurs : une monographie retient sa collection, une revue ou un préfixe DOI son éditeur. Leur suppression suit celle des publications : un référentiel vidé pendant le run disparaît dans le même run.

La phase traite toutes les sources et ignore `--sources` : une contribution change aussi hors de la normalisation, par les affiliations ou le recalcul d'une publication.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection, text

from infrastructure.db.scalars import scalar_int
from pipeline.runtime.context import OpenTransaction, Phase, PhaseContext
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect, quantity, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import waiting
from pipeline.task_runner import TaskStep, run_tasks
from pipeline.transformation.publications.lifecycle import purge_publications
from pipeline.transformation.publications.publication_perimeter import (
    refresh_publications_perimeter_evidence,
)
from pipeline.transformation.publishing.monographs import delete_empty_monographs
from pipeline.transformation.publishing.monographs.delete_empty_monographs import (
    run_delete_empty_monographs,
)
from pipeline.transformation.publishing.publication_counts import (
    refresh_publisher_publication_counts,
    refresh_serial_publication_counts,
)
from pipeline.transformation.publishing.publishers import delete_empty_publishers
from pipeline.transformation.publishing.publishers.delete_empty_publishers import (
    run_delete_empty_publishers,
)
from pipeline.transformation.publishing.serials import delete_empty_serials
from pipeline.transformation.publishing.serials.delete_empty_serials import (
    run_delete_empty_serials,
)
from pipeline.transformation.publishing.serials.serial_publishers import (
    refresh_serial_publishers,
)
from pipeline.transformation.structures.address_publication_count import (
    recompute_address_publication_count,
)

_PURGE_BATCH_SIZE = 5000


def count_contributions_in_perimeter(conn: Connection) -> int:
    """Nombre de contributions du périmètre rattachées à une personne."""
    return scalar_int(
        conn.execute(
            text("SELECT COUNT(*) FROM contributions WHERE person_id IS NOT NULL AND in_perimeter")
        )
    )


def refresh_contribution_structures(conn: Connection) -> None:
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY contribution_structures"))


def refresh_publication_structures(conn: Connection) -> None:
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY publication_structures"))


def refresh_publication_rors(conn: Connection) -> None:
    """ROR des auteurs de chaque publication, ancêtres compris : lit `publication_structures`, rafraîchie avant."""
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY publication_rors"))


@dataclass(frozen=True)
class FinalizePhase:
    # Suppressions des référentiels vides, dans l'ordre : (libellé, runner). Le câblage les fournit.
    empty_containers: tuple[tuple[str, Callable[[PhaseContext], PhaseMetrics]], ...] = ()

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute les tâches de la phase et retourne ses métriques : celles des référentiels vides, et un résumé."""

        def publications_in_perimeter(ctx: PhaseContext) -> PhaseMetrics:
            t0 = time.perf_counter()
            with ctx.open_tx() as conn:
                refresh_publications_perimeter_evidence(conn)
                in_perimeter = count_contributions_in_perimeter(conn)
            metrics = _timed(t0)
            metrics.details["in_perimeter"] = in_perimeter
            return metrics

        def structures(ctx: PhaseContext) -> PhaseMetrics:
            t0 = time.perf_counter()
            with ctx.open_tx() as conn:
                refresh_contribution_structures(conn)
                refresh_publication_structures(conn)
                refresh_publication_rors(conn)
            return _timed(t0)

        def purge(ctx: PhaseContext) -> PhaseMetrics:
            metrics = PhaseMetrics()
            metrics.details["purged"] = _purge_publications(ctx.open_tx)
            return metrics

        def serial_publishers(ctx: PhaseContext) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                changed = refresh_serial_publishers(conn)
            metrics = PhaseMetrics()
            metrics.report = (
                f"{quantity(changed, 'revue')} {inflect(changed, 'mise à jour', 'mises à jour')}"
            )
            return metrics

        def empty_containers(ctx: PhaseContext) -> PhaseMetrics:
            metrics = PhaseMetrics()
            _delete_empty_containers(self.empty_containers, metrics, ctx)
            return metrics

        def publication_counts(ctx: PhaseContext) -> PhaseMetrics:
            _refresh_publication_counts(ctx.open_tx, ctx.logger)
            return PhaseMetrics()

        sync_section = "Synchronisation des tables"
        by_task = run_tasks(
            "finalize",
            {
                "finalize.publications_in_perimeter": TaskStep(
                    publications_in_perimeter,
                    section=sync_section,
                    label="Périmètre des publications",
                ),
                "finalize.structures": TaskStep(
                    structures, section=sync_section, label="Structures des liens"
                ),
                "finalize.purge_publications": TaskStep(purge),
                "finalize.serial_publishers": TaskStep(
                    serial_publishers, label="Éditeur des revues"
                ),
                "finalize.delete_empty_containers": TaskStep(empty_containers),
                "finalize.publication_counts": TaskStep(publication_counts),
            },
            ctx,
        )
        metrics = by_task["finalize.delete_empty_containers"]
        metrics.details["summary"] = {
            "total_in_perimeter": by_task["finalize.publications_in_perimeter"].details[
                "in_perimeter"
            ],
            "publications_purged": by_task["finalize.purge_publications"].details["purged"],
        }
        return metrics


def _timed(t0: float) -> PhaseMetrics:
    """Métriques d'une tâche de synchronisation, dont le bilan est sa durée."""
    metrics = PhaseMetrics()
    metrics.report = f"{time.perf_counter() - t0:.1f}s"
    return metrics


def _purge_publications(open_tx: OpenTransaction) -> int:
    """Purge par lots, un commit par lot. Renvoie le nombre de publications supprimées."""
    n = 0
    with open_tx() as conn:
        while True:
            deleted = purge_publications(conn, limit=_PURGE_BATCH_SIZE)
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
    step(ctx.logger, "Référentiels vides")
    for index, (label, run) in enumerate(steps):
        sub = run(ctx)
        metrics.merge(sub)
        branch = LAST_BRANCH if index == len(steps) - 1 else BRANCH
        ctx.logger.info("%s%s : %s", branch, label, sub.report or "rien à faire")


def _refresh_publication_counts(open_tx: OpenTransaction, logger: logging.Logger) -> None:
    """Recalcule le nombre de publications de chaque adresse, revue et éditeur.

    Les trois se lisent des mêmes publications et contributions sources, stabilisées à ce point du pipeline.

    Chaque décompte dure : sa ligne annonce le travail en cours, puis cède la place à son résultat.
    """
    step(logger, "Recalcul des décomptes de publications")

    with waiting(f"{BRANCH}par adresse", logger) as line:
        with open_tx() as conn:
            addresses = recompute_address_publication_count(conn)
        line.conclude(
            f"{BRANCH}{quantity(addresses, 'adresse')} {inflect(addresses, 'mise à jour', 'mises à jour')}"
        )

    with waiting(f"{BRANCH}par revue", logger) as line:
        with open_tx() as conn:
            serials = refresh_serial_publication_counts(conn)
        line.conclude(
            f"{BRANCH}{quantity(serials, 'revue')} {inflect(serials, 'mise à jour', 'mises à jour')}"
        )

    with waiting(f"{LAST_BRANCH}par éditeur", logger) as line:
        with open_tx() as conn:
            publishers = refresh_publisher_publication_counts(conn)
        # « mis à jour » ne varie pas au pluriel, contrairement à « mise à jour ».
        line.conclude(f"{LAST_BRANCH}{quantity(publishers, 'éditeur')} mis à jour")


def build() -> Phase:
    return FinalizePhase(
        empty_containers=(
            (delete_empty_monographs.LABEL, _run_delete_empty_monographs),
            (delete_empty_serials.LABEL, _run_delete_empty_serials),
            (delete_empty_publishers.LABEL, _run_delete_empty_publishers),
        ),
    )


def _run_delete_empty_monographs(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        return run_delete_empty_monographs(conn, ctx.logger)


def _run_delete_empty_serials(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        return run_delete_empty_serials(conn, ctx.logger)


def _run_delete_empty_publishers(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        return run_delete_empty_publishers(conn, ctx.logger)
