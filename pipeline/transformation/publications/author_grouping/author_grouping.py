"""Phase `author_grouping` : groupes des contributions sources d'un même auteur dans chaque publication (`source_contribution_groups`, `source_contribution_group_members`).

Les publications de la file `publication_contributions_queue` se recalculent entièrement, par lots ; `--rebuild-author-grouping` les marque toutes ; les publications d'un lot se répartissent entre des processus, un par processeur disponible (`available_cpus`). Les doublons d'auteur d'un enregistrement source (`domain.publications.list_copies`) reçoivent `duplicate_of` et restent hors des groupes. Les autres contributions sources, tous rôles réunis, s'alignent par la règle de noms, le filtre d'ordre, l'ordre dans les trous et le modèle du résidu (`domain.publications.author_grouping`). Chaque groupe reprend l'identifiant du groupe en base avec lequel il partage le plus de contributions sources.

Tâche `author_grouping.build`.
"""

import logging
import math
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass, fields
from operator import attrgetter

from scipy.optimize import linear_sum_assignment
from sqlalchemy import Connection

from domain.publications.author_grouping import (
    Group,
    ResidualModel,
    SourceContribution,
    align_publication,
    plan_group_ids,
    with_known_first_name,
)
from domain.publications.list_copies import copied_source_contributions
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.cpu import available_cpus
from pipeline.runtime.observability.log_format import LAST_BRANCH, nothing_to_do, quantity, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress, waiting
from pipeline.task_runner import TaskStep, run_tasks
from pipeline.transformation.publications.author_grouping.residual_weights import (
    RESIDUAL_WEIGHTS,
)
from pipeline.transformation.publications.author_grouping.store import (
    BatchPlan,
    GroupRow,
    MembershipRow,
    SourceContributionGroupStore,
    SourceContributionRow,
)

# Plafonds d'un lot de publications : nombre de publications, nombre de contributions sources d'auteur chargées en mémoire.
BATCH_SIZE = 1000
BATCH_SOURCE_CONTRIBUTIONS = 200_000
_MODEL = ResidualModel(RESIDUAL_WEIGHTS)
# Source dont l'enregistrement source passe après les autres à longueur de liste égale : elle fonde un groupe seulement à défaut d'une autre.
DEFERRED_SOURCE = "scanr"


def publication_batches(publications: Sequence[tuple[int, int]]) -> list[list[int]]:
    """Lots de publications, dans l'ordre : un lot se ferme à `BATCH_SIZE` publications ou dès qu'il atteint `BATCH_SOURCE_CONTRIBUTIONS` contributions sources. `publications` : (publication, nombre de contributions sources)."""
    batches: list[list[int]] = []
    batch: list[int] = []
    source_contributions = 0
    for publication_id, count in publications:
        batch.append(publication_id)
        source_contributions += count
        if len(batch) >= BATCH_SIZE or source_contributions >= BATCH_SOURCE_CONTRIBUTIONS:
            batches.append(batch)
            batch, source_contributions = [], 0
    if batch:
        batches.append(batch)
    return batches


def assign(matrix: Sequence[Sequence[float]]) -> Iterable[tuple[int, int]]:
    """Affectation de gain maximal (algorithme hongrois)."""
    rows, cols = linear_sum_assignment([[-value for value in row] for row in matrix])
    return zip(rows.tolist(), cols.tolist(), strict=True)


def contributions_by_source_record(
    rows: Sequence[SourceContributionRow],
) -> dict[int, list[SourceContribution]]:
    """Contributions sources d'une publication par enregistrement source, tous rôles réunis. Une contribution source réduite à des initiales prend le prénom de la personne à laquelle un humain a rattaché son identifiant (`with_known_first_name`)."""
    source_records: dict[int, list[SourceContribution]] = {}
    for row in rows:
        first_name = with_known_first_name(row.first_name, row.known_first_name)
        source_records.setdefault(row.source_record, []).append(
            SourceContribution(
                row.id,
                row.source_record,
                row.position,
                row.last_name,
                first_name,
                row.orcid,
                row.idref,
            )
        )
    return source_records


def deferred_source_records(rows: Sequence[SourceContributionRow]) -> set[int]:
    """Enregistrements sources de `DEFERRED_SOURCE` parmi les contributions sources d'une publication."""
    return {row.source_record for row in rows if row.source == DEFERRED_SOURCE}


def group_publication(rows: Sequence[SourceContributionRow]) -> tuple[list[Group], dict[int, int]]:
    """Groupes des contributions sources d'une publication et doublons d'auteur (doublon → première occurrence de son nom), parmi les contributions sources qui ont une position. Les doublons restent hors des groupes."""
    source_records = contributions_by_source_record(rows)
    copies: dict[int, int] = {}
    for source_contributions in source_records.values():
        copies |= copied_source_contributions(source_contributions)
    kept = {
        n: [s for s in contributions if s.id not in copies]
        for n, contributions in source_records.items()
    }
    groups = align_publication(
        kept, model=_MODEL, assign=assign, deferred=deferred_source_records(rows)
    )
    return groups, copies


def _same_membership(stored: MembershipRow | None, planned: MembershipRow) -> bool:
    """L'appartenance en base vaut l'appartenance calculée. Le score et la marge sont comparés à la précision de leur colonne (`real`)."""
    if stored is None:
        return False

    def close(a: float | None, b: float | None) -> bool:
        return a is None if b is None else a is not None and math.isclose(a, b, rel_tol=1e-6)

    return (
        (stored.group, stored.source_record, stored.method)
        == (planned.group, planned.source_record, planned.method)
        and close(stored.score, planned.score)
        and close(stored.margin, planned.margin)
    )


def membership_changes(
    stored: Mapping[int, MembershipRow], planned: Sequence[MembershipRow]
) -> tuple[list[int], list[MembershipRow]]:
    """Contributions sources dont l'appartenance en base disparaît ou change, et appartenances à insérer. Une appartenance inchangée reste en place."""
    inserted = [m for m in planned if not _same_membership(stored.get(m.source_contribution), m)]
    kept = {m.source_contribution for m in planned}
    removed = [s for s in stored if s not in kept] + [m.source_contribution for m in inserted]
    return removed, inserted


# Contribution source (champs de `SourceContributionRow` dans l'ordre), appartenance (contribution source, enregistrement source, méthode, score, marge) et groupe (contribution source de référence, appartenances), en tuples : la forme la moins coûteuse à faire passer d'un processus à l'autre.
type SourceContributionTuple = tuple[int, int, str, int, int | None, str, str, str, str, str]
type MemberTuple = tuple[int, int, str, float | None, float | None]
type GroupTuple = tuple[int, list[MemberTuple]]
type Aligned = tuple[list[GroupTuple], dict[int, int]]

_SOURCE_CONTRIBUTION_FIELDS = attrgetter(*(f.name for f in fields(SourceContributionRow)))


def align_rows(rows: Sequence[SourceContributionTuple]) -> Aligned:
    """`group_publication` sur les contributions sources d'une publication en tuples, résultat en tuples."""
    groups, copies = group_publication([SourceContributionRow(*row) for row in rows])
    return [
        (
            g.reference.id,
            [
                (m.source_contribution, m.source_record, str(m.method), m.score, m.margin)
                for m in g.members
            ],
        )
        for g in groups
    ], copies


type Mapper = Callable[
    [
        Callable[[Sequence[SourceContributionTuple]], Aligned],
        Sequence[Sequence[SourceContributionTuple]],
    ],
    Iterator[Aligned],
]
"""Applique `align_rows` aux contributions sources de chaque publication et rend les résultats dans l'ordre : `map`, ou un pool de processus."""


def pool_mapper(pool: ProcessPoolExecutor, workers: int) -> Mapper:
    """`Mapper` qui répartit les publications d'un lot entre les `workers` processus de `pool`, par paquets de taille adaptée au lot."""

    def mapper(
        fn: Callable[[Sequence[SourceContributionTuple]], Aligned],
        items: Sequence[Sequence[SourceContributionTuple]],
    ) -> Iterator[Aligned]:
        return pool.map(fn, items, chunksize=max(1, len(items) // (4 * workers)))

    return mapper


def _plan_batch(
    store: SourceContributionGroupStore,
    publication_ids: Sequence[int],
    methods: Counter[str],
    on_publication: Callable[[], None],
    mapper: Mapper,
) -> BatchPlan:
    """Plan d'écriture d'un lot de publications. `on_publication` est appelé après chaque publication calculée."""
    rows_by_publication: dict[int, list[SourceContributionTuple]] = {}
    positions: dict[int, int | None] = {}
    for row in store.fetch_source_contributions(publication_ids):
        rows_by_publication.setdefault(row.publication_id, []).append(
            _SOURCE_CONTRIBUTION_FIELDS(row)
        )
        positions[row.id] = row.position
    existing, stored = store.fetch_groups(publication_ids)
    planned: list[tuple[int, GroupTuple, int | None]] = []
    unmatched: list[int] = []
    recomposed: list[int] = []
    copies: dict[int, int] = {}
    results = mapper(align_rows, [rows_by_publication.get(p, []) for p in publication_ids])
    for publication_id, (groups, publication_copies) in zip(publication_ids, results, strict=True):
        copies |= publication_copies
        old = {
            gid: frozenset(contributions)
            for gid, contributions in existing.get(publication_id, {}).items()
        }
        new = [frozenset(m[0] for m in members) for _, members in groups]
        ids = plan_group_ids(old, new)
        planned += [(publication_id, g, gid) for g, gid in zip(groups, ids, strict=True)]
        recomposed += [
            gid
            for gid, members in zip(ids, new, strict=True)
            if gid is not None and old[gid] != members
        ]
        unmatched += sorted(set(old) - {gid for gid in ids if gid is not None})
        on_publication()
    fresh = iter(store.group_ids(sum(1 for *_, gid in planned if gid is None)))
    group_rows: list[GroupRow] = []
    memberships: list[MembershipRow] = []
    for publication_id, (reference, members), gid in planned:
        existing_id = gid is not None
        group_id = gid if gid is not None else next(fresh)
        group_rows.append(GroupRow(group_id, publication_id, positions[reference], existing_id))
        for source_contribution, source_record, method, score, margin in members:
            methods[method] += 1
            memberships.append(
                MembershipRow(source_contribution, group_id, source_record, method, score, margin)
            )
    removed, inserted = membership_changes(stored, memberships)
    return BatchPlan(publication_ids, group_rows, removed, inserted, unmatched, recomposed, copies)


def regroup(
    store: SourceContributionGroupStore,
    publication_ids: Sequence[int],
    methods: Counter[str] | None = None,
    on_publication: Callable[[], None] = lambda: None,
    mapper: Mapper = map,
) -> int:
    """Recalcule et écrit les groupes et les doublons d'auteur de ces publications, sans commit. Rend le nombre de groupes écrits ; `methods` compte les appartenances par origine."""
    plan = _plan_batch(
        store,
        publication_ids,
        methods if methods is not None else Counter(),
        on_publication,
        mapper,
    )
    store.write(plan)
    return len(plan.groups)


def build_groups(
    conn: Connection,
    store: SourceContributionGroupStore,
    logger: logging.Logger,
    *,
    rebuild: bool = False,
) -> PhaseMetrics:
    """Recalcule les groupes des publications en file, lot par lot, avec un commit par lot. Chaque lot supprime ses marquages traités avant son commit. Rafraîchit ensuite le recouvrement des listes d'auteurs. Les groupes d'une publication supprimée disparaissent avec elle (`ON DELETE CASCADE`).

    `rebuild` marque d'abord toutes les publications, pour appliquer une évolution des règles d'alignement sur tout le stock. Le marquage est commité aussitôt : un run interrompu reprend les publications restantes.
    """
    if rebuild:
        marked = store.mark_all()
        conn.commit()
        step(logger, "%s marquées à regrouper", quantity(marked, "publication"))
    dirty = store.snapshot_queued_publications()
    publication_ids = [publication_id for publication_id, _ in dirty]
    step(logger, "auteurs à aligner dans %s", quantity(len(publication_ids), "publication"))
    if not publication_ids:
        store.drop_snapshot()
        nothing_to_do(logger)
        return PhaseMetrics()
    metrics = PhaseMetrics(seen=len(publication_ids))
    methods: Counter[str] = Counter()
    group_count = 0
    workers = min(available_cpus(), len(publication_ids))
    with (
        ProcessPoolExecutor(max_workers=workers) if workers > 1 else nullcontext() as pool,
        track_progress(len(publication_ids), LAST_BRANCH.rstrip(), logger) as progress,
    ):
        mapper: Mapper = pool_mapper(pool, workers) if pool is not None else map
        for batch in publication_batches(dirty):
            group_count += regroup(store, batch, methods, progress.advance, mapper)
            store.delete_processed_marks(batch)
            conn.commit()
    store.drop_snapshot()
    step(logger, "Recouvrement des listes d'auteurs")
    t0 = time.perf_counter()
    with waiting(LAST_BRANCH, logger) as line:
        store.refresh_alignment()
        conn.commit()
        line.conclude(f"{LAST_BRANCH}Terminé en {time.perf_counter() - t0:.1f}s")
    metrics.add(updated=len(publication_ids))
    metrics.details["summary"] = {
        "publications": len(publication_ids),
        "groups": group_count,
        **{str(method): count for method, count in methods.items()},
    }
    metrics.report = (
        f"{quantity(len(publication_ids), 'publication')}, {quantity(group_count, 'groupe')}"
    )
    return metrics


@dataclass(frozen=True)
class AuthorGroupingPhase:
    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Recalcule les groupes des publications marquées, puis les attributs de tous les groupes : l'affiliation d'un membre change sans que son groupe change."""

        def build_task(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                return build_groups(
                    conn,
                    SourceContributionGroupStore(conn),
                    ctx.logger,
                    rebuild=ctx.options.rebuild_author_grouping,
                )

        def attributes_task(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                updated = SourceContributionGroupStore(conn).propagate_attributes()
            metrics = PhaseMetrics(updated=updated)
            metrics.report = quantity(updated, "groupe réécrit", "groupes réécrits")
            return metrics

        by_task = run_tasks(
            "author_grouping",
            {
                "author_grouping.build": TaskStep(build_task, label="Bilan"),
                "author_grouping.attributes": TaskStep(
                    attributes_task, label="Attributs des groupes"
                ),
            },
            ctx,
        )
        metrics = by_task["author_grouping.build"]
        metrics.details["attributes_updated"] = by_task["author_grouping.attributes"].updated
        return metrics


def build() -> Phase:
    return AuthorGroupingPhase()
