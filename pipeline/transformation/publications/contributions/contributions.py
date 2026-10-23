"""Phase `contributions` : construction de la table `contributions`.

Tâches (`pipeline.graph`), chacune dans sa transaction :

1. **build** — consolide les `source_contributions` en contributions (une entrée par couple publication × personne). Sa maintenance `ANALYZE contributions` précède la propagation.
2. **propagate**, **publications_in_perimeter**, **structures** — recomposent les attributs des contributions (indices de l'entrée dans le périmètre compris), le périmètre des publications et les matviews `contribution_structures`, `publication_structures`.
3. **purge des orphelines** — supprime les publications rétrogradées à zéro contribution (défense en profondeur).
4. **référentiels vides** — supprime les monographies, revues et éditeurs que plus rien ne référence, dans cet ordre : une monographie maintient sa collection, une revue ou un préfixe DOI son éditeur. Elle suit les dernières suppressions de publications, donc un référentiel vidé dans le run est supprimé dans le même run.
5. **refresh des `publication_count`** — recalcule le nombre de publications de chaque adresse, revue et éditeur.

La phase reconsolide toutes les sources à chaque run et ignore `--sources` : une contribution source change aussi par d'autres voies que sa normalisation, comme la repopulation des affiliations ou le recalcul des métadonnées d'une publication.

Le build est incrémental et convergent (add + prune + recompute en une passe).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection, text

from pipeline.runtime.context import OpenTransaction, Phase, PhaseContext
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect, quantity, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import waiting
from pipeline.task_runner import TaskStep, run_tasks
from pipeline.transformation.publications.contributions.address_publication_count import (
    recompute_address_publication_count,
)
from pipeline.transformation.publications.contributions.build_contributions import (
    build as build_contributions,
)
from pipeline.transformation.publications.contributions.contributions_queries import (
    ContributionsBuild,
)
from pipeline.transformation.publishing.journals import delete_empty_journals
from pipeline.transformation.publishing.journals.delete_empty_journals import (
    run_delete_empty_journals,
)
from pipeline.transformation.publishing.monographs import delete_empty_monographs
from pipeline.transformation.publishing.monographs.delete_empty_monographs import (
    run_delete_empty_monographs,
)
from pipeline.transformation.publishing.publication_counts import (
    refresh_journal_publication_counts,
    refresh_publisher_publication_counts,
)
from pipeline.transformation.publishing.publishers import delete_empty_publishers
from pipeline.transformation.publishing.publishers.delete_empty_publishers import (
    run_delete_empty_publishers,
)

_PURGE_BATCH_SIZE = 5000


def purge_orphan_publications(conn: Connection, *, limit: int | None = None) -> int:
    """Supprime les publications sans aucune contribution, un lot de `limit` au plus. Retourne le nombre supprimé.

    La réconciliation crée une publication pour une partition d'orphelins du périmètre seulement : une publication naît avec au moins une contribution attendu. Elle tombe à zéro contribution quand sa dernière contribution source du périmètre disparaît (personne détachée, structure sortie du périmètre, forme de nom rejetée). `publication_subjects` suit par `ON DELETE CASCADE`.
    """
    limit_clause = "LIMIT :lim" if limit is not None else ""
    return conn.execute(
        text(
            f"""
            DELETE FROM publications
            WHERE id IN (
                SELECT p.id FROM publications p
                WHERE NOT EXISTS (
                    SELECT 1 FROM contributions a WHERE a.publication_id = p.id
                )
                {limit_clause}
            )
            """
        ),
        {"lim": limit} if limit is not None else {},
    ).rowcount


@dataclass(frozen=True)
class ContributionsPhase:
    build_queries: ContributionsBuild
    # Suppressions des référentiels vides, dans l'ordre : (libellé, runner). Le câblage les fournit.
    empty_containers: tuple[tuple[str, Callable[[PhaseContext], PhaseMetrics]], ...] = ()

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute les tâches de la phase et retourne les métriques du build."""
        queries = self.build_queries

        def build(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                return build_contributions(conn, queries, ctx.logger)

        def propagate(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            t0 = time.perf_counter()
            with ctx.open_tx() as conn:
                queries.propagate_contribution_attributes(conn)
                in_perimeter = queries.count_contributions_in_perimeter(conn)
            metrics = _timed(t0)
            metrics.details["in_perimeter"] = in_perimeter
            return metrics

        def publications_in_perimeter(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            t0 = time.perf_counter()
            with ctx.open_tx() as conn:
                queries.refresh_publications_perimeter_evidence(conn)
            return _timed(t0)

        def structures(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            t0 = time.perf_counter()
            with ctx.open_tx() as conn:
                queries.refresh_contribution_structures(conn)
                queries.refresh_publication_structures(conn)
            return _timed(t0)

        def purge(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            metrics = PhaseMetrics()
            metrics.details["purged"] = _purge_orphan_publications(ctx.open_tx)
            return metrics

        def empty_containers(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            metrics = PhaseMetrics()
            _delete_empty_containers(self.empty_containers, metrics, ctx)
            return metrics

        def publication_counts(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            _refresh_publication_counts(ctx.open_tx, ctx.logger)
            return PhaseMetrics()

        sync_section = "Synchronisation des tables"
        by_task = run_tasks(
            "contributions",
            {
                "contributions.build": TaskStep(build),
                "contributions.propagate": TaskStep(
                    propagate, section=sync_section, label="Attributs des liens"
                ),
                "contributions.publications_in_perimeter": TaskStep(
                    publications_in_perimeter,
                    section=sync_section,
                    label="Périmètre des publications",
                ),
                "contributions.structures": TaskStep(
                    structures, section=sync_section, label="Structures des liens"
                ),
                "contributions.purge_orphan_publications": TaskStep(purge),
                "contributions.delete_empty_containers": TaskStep(empty_containers),
                "contributions.publication_counts": TaskStep(publication_counts),
            },
            ctx,
        )
        metrics = by_task["contributions.build"]
        metrics.merge(by_task["contributions.delete_empty_containers"])
        summary = metrics.details["summary"]
        if isinstance(summary, dict):
            summary["total_in_perimeter"] = by_task["contributions.propagate"].details[
                "in_perimeter"
            ]
            summary["publications_purged"] = by_task[
                "contributions.purge_orphan_publications"
            ].details["purged"]
        return metrics


def _timed(t0: float) -> PhaseMetrics:
    """Métriques d'une tâche de synchronisation, dont le bilan est sa durée."""
    metrics = PhaseMetrics()
    metrics.report = f"{time.perf_counter() - t0:.1f}s"
    return metrics


def _purge_orphan_publications(open_tx: OpenTransaction) -> int:
    """Purge par lots (commit par chunk). Retourne le nombre de publications supprimées."""
    n = 0
    with open_tx() as conn:
        while True:
            deleted = purge_orphan_publications(conn, limit=_PURGE_BATCH_SIZE)
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

    Les trois se lisent des mêmes publications et contributions sources, stabilisées à ce point du pipeline. Le décompte des éditeurs somme celui des revues, donc le suit.

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
            journals = refresh_journal_publication_counts(conn)
        line.conclude(
            f"{BRANCH}{quantity(journals, 'revue')} {inflect(journals, 'mise à jour', 'mises à jour')}"
        )

    with waiting(f"{LAST_BRANCH}par éditeur", logger) as line:
        with open_tx() as conn:
            publishers = refresh_publisher_publication_counts(conn)
        # « mis à jour » ne varie pas au pluriel, contrairement à « mise à jour ».
        line.conclude(f"{LAST_BRANCH}{quantity(publishers, 'éditeur')} mis à jour")


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    return ContributionsPhase(
        ContributionsBuild(),
        empty_containers=(
            (delete_empty_monographs.LABEL, _run_delete_empty_monographs),
            (delete_empty_journals.LABEL, _run_delete_empty_journals),
            (delete_empty_publishers.LABEL, _run_delete_empty_publishers),
        ),
    )


def _run_delete_empty_monographs(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        return run_delete_empty_monographs(conn, ctx.logger)


def _run_delete_empty_journals(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        return run_delete_empty_journals(conn, ctx.logger)


def _run_delete_empty_publishers(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        return run_delete_empty_publishers(conn, ctx.logger)
