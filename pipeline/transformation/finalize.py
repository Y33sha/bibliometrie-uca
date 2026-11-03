"""Phase `finalize` : données dérivées des contributions, après la résolution des personnes. Chaque tâche a sa transaction.

La phase recompose le périmètre des publications et les vues matérialisées des structures, supprime les publications sans enregistrement source ou sans contribution, recalcule l'éditeur des revues, supprime les référentiels vides, puis recompte les publications des adresses, revues et éditeurs.

Les référentiels vides se suppriment dans l'ordre monographies, revues, éditeurs : une monographie retient sa collection, une revue ou un préfixe DOI son éditeur. Leur suppression suit celle des publications : un référentiel vidé pendant le run disparaît dans le même run.

La phase traite toutes les sources et ignore `--sources` : une contribution change aussi hors de la normalisation, par les affiliations ou le recalcul d'une publication.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping

from sqlalchemy import Connection, text

from infrastructure.db.scalars import scalar_int
from pipeline.graph import task
from pipeline.runtime.context import OpenTransaction, PhaseContext
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect, quantity, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import waiting
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
    """Renvoie le nombre de contributions du périmètre rattachées à une personne."""
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
    """Rafraîchit les ROR des auteurs de chaque publication, ancêtres compris. Lit `publication_structures`, rafraîchie avant."""
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY publication_rors"))


def _publications_in_perimeter(ctx: PhaseContext) -> PhaseMetrics:
    t0 = time.perf_counter()
    with ctx.open_tx() as conn:
        refresh_publications_perimeter_evidence(conn)
        in_perimeter = count_contributions_in_perimeter(conn)
    metrics = _timed(t0)
    metrics.details["in_perimeter"] = in_perimeter
    return metrics


def _structures(ctx: PhaseContext) -> PhaseMetrics:
    t0 = time.perf_counter()
    with ctx.open_tx() as conn:
        refresh_contribution_structures(conn)
        refresh_publication_structures(conn)
        refresh_publication_rors(conn)
    return _timed(t0)


def _purge(ctx: PhaseContext) -> PhaseMetrics:
    metrics = PhaseMetrics()
    metrics.details["purged"] = _purge_publications(ctx.open_tx)
    return metrics


def _serial_publishers(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        changed = refresh_serial_publishers(conn)
    metrics = PhaseMetrics()
    metrics.report = (
        f"{quantity(changed, 'revue')} {inflect(changed, 'mise à jour', 'mises à jour')}"
    )
    return metrics


def _empty_containers(ctx: PhaseContext) -> PhaseMetrics:
    metrics = PhaseMetrics()
    _delete_empty_containers(_EMPTY_CONTAINERS, metrics, ctx)
    return metrics


def _publication_counts(ctx: PhaseContext) -> PhaseMetrics:
    _refresh_publication_counts(ctx.open_tx, ctx.logger)
    return PhaseMetrics()


def _timed(t0: float) -> PhaseMetrics:
    """Renvoie les métriques d'une tâche de synchronisation, avec sa durée pour bilan."""
    metrics = PhaseMetrics()
    metrics.report = f"{time.perf_counter() - t0:.1f}s"
    return metrics


def _purge_publications(open_tx: OpenTransaction) -> int:
    """Purge les publications par lots, un commit par lot. Renvoie le nombre de publications supprimées."""
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
    """Supprime les référentiels vides. Chaque suppression écrit sa ligne et reporte ses compteurs à la phase."""
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

    Les trois décomptes lisent les mêmes publications et contributions sources, stables à ce point du pipeline.

    Chaque décompte est long : sa ligne annonce le travail en cours, puis affiche son résultat.
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


def _run_delete_empty_monographs(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        return run_delete_empty_monographs(conn, ctx.logger)


def _run_delete_empty_serials(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        return run_delete_empty_serials(conn, ctx.logger)


def _run_delete_empty_publishers(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        return run_delete_empty_publishers(conn, ctx.logger)


_EMPTY_CONTAINERS: tuple[tuple[str, Callable[[PhaseContext], PhaseMetrics]], ...] = (
    (delete_empty_monographs.LABEL, _run_delete_empty_monographs),
    (delete_empty_serials.LABEL, _run_delete_empty_serials),
    (delete_empty_publishers.LABEL, _run_delete_empty_publishers),
)
"""Suppressions des référentiels vides, dans l'ordre : (libellé, fonction)."""


TASKS = (
    task(
        "finalize.publications_in_perimeter",
        reads=(
            "contributions.person_id",
            "contributions.perimeter_evidence",
            "contributions.roles",
            "persons.exclusion",
            "publications.id",
        ),
        writes=("publications.in_perimeter",),
        # Lignes supprimées plus loin dans le même run par `finalize.purge_publications`.
        previous_run=("publications.id",),
        run=_publications_in_perimeter,
        section="Synchronisation des tables",
        label="Périmètre des publications",
    ),
    task(
        "finalize.structures",
        reads=(
            "source_contribution_structures",
            "contributions.id",
            "contributions.publication_id",
            "contributions.person_id",
            "contributions.roles",
            "aligned_source_contributions",
            "persons.exclusion",
            "source_contribution_rors",
            "ror_relations",
            "structures.ror_id",
        ),
        writes=("contribution_structures", "publication_structures", "publication_rors"),
        run=_structures,
        section="Synchronisation des tables",
        label="Structures des liens",
    ),
    task(
        "finalize.purge_publications",
        reads=(
            "publications.id",
            "source_records.publication_id",
            "contributions.id",
            "contributions.publication_id",
            "contributions.person_id",
        ),
        writes=("publications.id",),
        run=_purge,
    ),
    task(
        "finalize.serial_publishers",
        reads=(
            "serials.id",
            "publications.serial_id",
            "publications.monograph_id",
            "publications.publisher_id",
            "publications.publication_year",
            "monographs.serial_id",
        ),
        writes=("serials.publisher_id",),
        # Les revues et les monographies supprimées ensuite par `delete_empty_containers` n'ont pas de publication : leur suppression ne change aucun éditeur.
        previous_run=("serials.id", "monographs.serial_id"),
        run=_serial_publishers,
        label="Éditeur des revues",
    ),
    task(
        "finalize.delete_empty_containers",
        reads=(
            "monographs.id",
            "monographs.serial_id",
            "serials.id",
            "serials.publisher_id",
            "publishers.id",
            "source_records.serial_id",
            "source_records.monograph_id",
            "source_records.publisher_id",
            "publications.serial_id",
            "publications.monograph_id",
            "publications.publisher_id",
            "apc_payments",
            "doi_prefixes.publisher_id",
            "serial_title_decisions",
            # ISSN cités par la série d'un enregistrement source, ou reliés à un autre titre.
            "serial_issns",
            "source_records.biblio",
            "issn_links",
        ),
        writes=("monographs.id", "serials.id", "publishers.id", "serial_issns"),
        run=_empty_containers,
    ),
    task(
        "finalize.publication_counts",
        reads=(
            "addresses.id",
            "source_contribution_addresses",
            "source_contributions.source_record_id",
            "source_records.publication_id",
            "source_records.serial_id",
            "serials.id",
            "publishers.id",
            "publications.id",
            "publications.in_perimeter",
            "publications.serial_id",
            "publications.publisher_id",
        ),
        writes=(
            "addresses.publication_count",
            "serials.publication_count",
            "publishers.publication_count",
        ),
        previous_run=("addresses",),
        run=_publication_counts,
    ),
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie les métriques de la phase : celles des référentiels vides, et un résumé."""
    metrics = by_task["finalize.delete_empty_containers"]
    metrics.details["summary"] = {
        "total_in_perimeter": by_task["finalize.publications_in_perimeter"].details["in_perimeter"],
        "publications_purged": by_task["finalize.purge_publications"].details["purged"],
    }
    return metrics
