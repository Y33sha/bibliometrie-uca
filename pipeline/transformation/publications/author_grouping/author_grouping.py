"""Phase `author_grouping` : regroupement, dans chaque publication, des contributions sources d'un même auteur en contributions (`contributions`, `aligned_source_contributions`).

Les publications de la file `publication_contributions_queue` se recalculent entièrement, par lots. `--rebuild-author-grouping` marque toutes les publications. Les publications d'un lot se répartissent entre des processus, un par processeur disponible (`available_cpus`). Les doublons d'auteur d'un enregistrement source (`domain.contributions.author_duplicates`) reçoivent `duplicate_of` et restent hors des contributions. Les autres contributions sources, tous rôles réunis, s'alignent selon `domain.contributions.author_grouping`. Chaque contribution reprend l'identifiant de la contribution en base avec laquelle elle partage le plus de contributions sources.
"""

import logging
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from contextlib import nullcontext
from dataclasses import fields
from operator import attrgetter

from sqlalchemy import Connection

from domain.contributions.author_duplicates import duplicate_source_contributions
from domain.contributions.author_grouping import (
    Contribution,
    SourceContribution,
    align_publication,
    plan_contribution_ids,
    with_known_first_name,
)
from pipeline.graph import Task
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.cpu import available_cpus
from pipeline.runtime.observability.log_format import LAST_BRANCH, nothing_to_do, quantity, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress, waiting
from pipeline.transformation.publications.author_grouping.store import (
    AuthorGroupingStore,
    BatchPlan,
    ContributionRow,
    MembershipRow,
    SourceContributionRow,
)

# Plafonds d'un lot de publications : nombre de publications, nombre de contributions sources d'auteur chargées en mémoire.
BATCH_SIZE = 1000
BATCH_SOURCE_CONTRIBUTIONS = 200_000
DEFERRED_SOURCE = "scanr"
"""Source classée après les autres à longueur de liste égale : elle fonde une contribution seulement à défaut d'une autre source."""


def publication_batches(publications: Sequence[tuple[int, int]]) -> list[list[int]]:
    """Découpe les publications en lots, dans l'ordre. Un lot se ferme à `BATCH_SIZE` publications ou à `BATCH_SOURCE_CONTRIBUTIONS` contributions sources.

    Args:
        publications: paires (publication, nombre de contributions sources).
    """
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


def contributions_by_source_record(
    rows: Sequence[SourceContributionRow],
) -> dict[int, list[SourceContribution]]:
    """Regroupe les contributions sources d'une publication par enregistrement source, tous rôles réunis. Une contribution source réduite à des initiales prend le prénom de la personne rattachée par un humain à son identifiant (`with_known_first_name`)."""
    source_records: dict[int, list[SourceContribution]] = {}
    for row in rows:
        first_name = with_known_first_name(row.first_name, row.known_first_name)
        source_records.setdefault(row.source_record, []).append(
            SourceContribution(row.id, row.source_record, row.position, row.last_name, first_name)
        )
    return source_records


def deferred_source_records(rows: Sequence[SourceContributionRow]) -> set[int]:
    """Renvoie les enregistrements sources de `DEFERRED_SOURCE` parmi les contributions sources d'une publication."""
    return {row.source_record for row in rows if row.source == DEFERRED_SOURCE}


def align_publication_contributions(
    rows: Sequence[SourceContributionRow],
) -> tuple[list[Contribution], dict[int, int]]:
    """Renvoie les contributions d'une publication et ses doublons d'auteur (doublon → première occurrence de son nom), parmi les contributions sources à position. Les doublons restent hors des contributions."""
    source_records = contributions_by_source_record(rows)
    duplicates: dict[int, int] = {}
    for source_contributions in source_records.values():
        duplicates |= duplicate_source_contributions(source_contributions)
    kept = {
        n: [s for s in record_contributions if s.id not in duplicates]
        for n, record_contributions in source_records.items()
    }
    contributions = align_publication(kept, deferred=deferred_source_records(rows))
    return contributions, duplicates


def membership_changes(
    stored: Mapping[int, MembershipRow], planned: Sequence[MembershipRow]
) -> tuple[list[int], list[MembershipRow]]:
    """Renvoie les contributions sources à appartenance disparue ou changée, et les appartenances à insérer. Une appartenance inchangée reste en place."""
    inserted = [m for m in planned if stored.get(m.source_contribution) != m]
    kept = {m.source_contribution for m in planned}
    removed = [s for s in stored if s not in kept] + [m.source_contribution for m in inserted]
    return removed, inserted


# Échanges entre processus, en tuples : contribution source (champs de `SourceContributionRow`), appartenance (contribution source, enregistrement source, méthode), contribution (référence, appartenances).
type SourceContributionTuple = tuple[int, int, str, int, int | None, str, str, str]
type MemberTuple = tuple[int, int, str]
type ContributionTuple = tuple[int, list[MemberTuple]]
type Aligned = tuple[list[ContributionTuple], dict[int, int]]

_SOURCE_CONTRIBUTION_FIELDS = attrgetter(*(f.name for f in fields(SourceContributionRow)))


def align_rows(rows: Sequence[SourceContributionTuple]) -> Aligned:
    """Applique `align_publication_contributions` aux contributions sources d'une publication, en tuples à l'entrée comme à la sortie."""
    contributions, duplicates = align_publication_contributions(
        [SourceContributionRow(*row) for row in rows]
    )
    return [
        (
            g.reference.id,
            [(m.source_contribution, m.source_record, str(m.method)) for m in g.members],
        )
        for g in contributions
    ], duplicates


type Mapper = Callable[
    [
        Callable[[Sequence[SourceContributionTuple]], Aligned],
        Sequence[Sequence[SourceContributionTuple]],
    ],
    Iterator[Aligned],
]
"""Application de `align_rows` aux contributions sources de chaque publication, résultats dans l'ordre : `map`, ou un pool de processus."""


def pool_mapper(pool: ProcessPoolExecutor, workers: int) -> Mapper:
    """Renvoie un `Mapper` qui répartit les publications d'un lot entre les `workers` processus de `pool`, par paquets de taille adaptée au lot."""

    def mapper(
        fn: Callable[[Sequence[SourceContributionTuple]], Aligned],
        items: Sequence[Sequence[SourceContributionTuple]],
    ) -> Iterator[Aligned]:
        return pool.map(fn, items, chunksize=max(1, len(items) // (4 * workers)))

    return mapper


def _plan_batch(
    store: AuthorGroupingStore,
    publication_ids: Sequence[int],
    methods: Counter[str],
    on_publication: Callable[[], None],
    mapper: Mapper,
) -> BatchPlan:
    """Calcule le plan d'écriture d'un lot de publications.

    Args:
        on_publication: appelé après chaque publication calculée.
    """
    rows_by_publication: dict[int, list[SourceContributionTuple]] = {}
    positions: dict[int, int | None] = {}
    for row in store.fetch_source_contributions(publication_ids):
        rows_by_publication.setdefault(row.publication_id, []).append(
            _SOURCE_CONTRIBUTION_FIELDS(row)
        )
        positions[row.id] = row.position
    existing, stored = store.fetch_contributions(publication_ids)
    planned: list[tuple[int, ContributionTuple, int | None]] = []
    unmatched: list[int] = []
    recomposed: list[int] = []
    duplicates: dict[int, int] = {}
    results = mapper(align_rows, [rows_by_publication.get(p, []) for p in publication_ids])
    for publication_id, (contributions, publication_duplicates) in zip(
        publication_ids, results, strict=True
    ):
        duplicates |= publication_duplicates
        old = {gid: frozenset(members) for gid, members in existing.get(publication_id, {}).items()}
        new = [frozenset(m[0] for m in members) for _, members in contributions]
        ids = plan_contribution_ids(old, new)
        planned += [(publication_id, g, gid) for g, gid in zip(contributions, ids, strict=True)]
        recomposed += [
            gid
            for gid, members in zip(ids, new, strict=True)
            if gid is not None and old[gid] != members
        ]
        unmatched += sorted(set(old) - {gid for gid in ids if gid is not None})
        on_publication()
    fresh = iter(store.new_contribution_ids(sum(1 for *_, gid in planned if gid is None)))
    contribution_rows: list[ContributionRow] = []
    memberships: list[MembershipRow] = []
    for publication_id, (reference, members), gid in planned:
        existing_id = gid is not None
        contribution_id = gid if gid is not None else next(fresh)
        contribution_rows.append(
            ContributionRow(contribution_id, publication_id, positions[reference], existing_id)
        )
        for source_contribution, source_record, method in members:
            methods[method] += 1
            memberships.append(
                MembershipRow(source_contribution, contribution_id, source_record, method)
            )
    removed, inserted = membership_changes(stored, memberships)
    return BatchPlan(
        publication_ids, contribution_rows, removed, inserted, unmatched, recomposed, duplicates
    )


def realign(
    store: AuthorGroupingStore,
    publication_ids: Sequence[int],
    methods: Counter[str] | None = None,
    on_publication: Callable[[], None] = lambda: None,
    mapper: Mapper = map,
) -> int:
    """Recalcule et écrit les contributions et les doublons d'auteur de ces publications, sans commit. Renvoie le nombre de contributions écrites.

    Args:
        methods: compteur des appartenances par origine, incrémenté au passage.
    """
    plan = _plan_batch(
        store,
        publication_ids,
        methods if methods is not None else Counter(),
        on_publication,
        mapper,
    )
    store.write(plan)
    return len(plan.contributions)


def build_contributions(
    conn: Connection,
    store: AuthorGroupingStore,
    logger: logging.Logger,
    *,
    rebuild: bool = False,
) -> PhaseMetrics:
    """Recalcule les contributions des publications en file, avec un commit par lot. Chaque lot supprime ses marquages traités avant son commit. Rafraîchit ensuite le recouvrement des listes d'auteurs. Les contributions d'une publication supprimée disparaissent avec elle (`ON DELETE CASCADE`).

    Args:
        rebuild: marque d'abord toutes les publications et commite le marquage ; un run interrompu reprend les publications restantes.
    """
    if rebuild:
        marked = store.mark_all()
        conn.commit()
        step(logger, "%s marquées à réaligner", quantity(marked, "publication"))
    dirty = store.snapshot_queued_publications()
    publication_ids = [publication_id for publication_id, _ in dirty]
    step(logger, "auteurs à aligner dans %s", quantity(len(publication_ids), "publication"))
    if not publication_ids:
        store.delete_processed_marks()
        store.drop_snapshot()
        nothing_to_do(logger)
        return PhaseMetrics()
    metrics = PhaseMetrics(seen=len(publication_ids))
    methods: Counter[str] = Counter()
    contribution_count = 0
    workers = min(available_cpus(), len(publication_ids))
    with (
        ProcessPoolExecutor(max_workers=workers) if workers > 1 else nullcontext() as pool,
        track_progress(len(publication_ids), LAST_BRANCH.rstrip(), logger) as progress,
    ):
        mapper: Mapper = pool_mapper(pool, workers) if pool is not None else map
        for batch in publication_batches(dirty):
            contribution_count += realign(store, batch, methods, progress.advance, mapper)
            store.delete_processed_marks(batch)
            conn.commit()
    # Marquages relevés des publications supprimées.
    store.delete_processed_marks()
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
        "groups": contribution_count,
        **{str(method): count for method, count in methods.items()},
    }
    metrics.report = f"{quantity(len(publication_ids), 'publication')}, {quantity(contribution_count, 'contribution')}"
    return metrics


def _build(ctx: PhaseContext) -> PhaseMetrics:
    """Recalcule les contributions des publications en file."""
    with ctx.open_tx() as conn:
        return build_contributions(
            conn,
            AuthorGroupingStore(conn),
            ctx.logger,
            rebuild=ctx.options.rebuild_author_grouping,
        )


def _attributes(ctx: PhaseContext) -> PhaseMetrics:
    """Recalcule les attributs des contributions en file. Les attributs ont leur propre file : l'affiliation d'une contribution source change sans changer sa contribution."""
    step(ctx.logger, "Attributs des contributions")
    t0 = time.perf_counter()
    with (
        waiting(f"{LAST_BRANCH}en cours", ctx.logger) as line,
        ctx.open_tx() as conn,
    ):
        queued, updated = AuthorGroupingStore(conn).propagate_attributes()
        line.conclude(
            f"{LAST_BRANCH}{quantity(queued, 'contribution examinée', 'contributions examinées')},"
            f" {quantity(updated, 'mise à jour', 'mises à jour')}"
            f" en {time.perf_counter() - t0:.1f} s"
        )
    metrics = PhaseMetrics(seen=queued, updated=updated)
    metrics.report = quantity(updated, "contribution mise à jour", "contributions mises à jour")
    return metrics


TASKS = (
    Task(
        "build",
        reads=(
            "publications.id",
            "publication_contributions_queue",
            "source_records.publication_id",
            "source_records.source_id",
            "source_records.corrections",
            "source_contributions.id",
            "source_contributions.source_record_id",
            "source_contributions.author_position",
            "source_contributions.collective",
            "source_contributions.contributor_information_id",
            "source_contributions.neutralized_identifiers",
            "contributor_information",
            # Prénom de la personne à laquelle un humain a rattaché l'identifiant d'une contribution source.
            "person_identifiers",
            "persons",
            "contributions",
            "aligned_source_contributions",
        ),
        writes=(
            "contributions.id",
            "contributions.reference_position",
            "aligned_source_contributions.id",
            "source_contributions.duplicate_of",
            "publication_contributions_queue",
            "contribution_attributes_queue",
            # Une contribution rattachée dont les contributions sources changent est marquée pour la redécision de sa personne.
            "contribution_resolution_queue",
            "publication_author_alignment",
        ),
        previous_run=(
            # Publications, contributions et alignements supprimés, enregistrements sources détachés par `finalize.purge_publications`.
            "publications.id",
            "contributions",
            "aligned_source_contributions",
            "source_records.publication_id",
            # Marquages retirés par la tâche elle-même.
            "publication_contributions_queue",
            # Personnes, identifiants, neutralisations et personnes des contributions, écrits par la phase `persons`.
            "person_identifiers",
            "persons",
            "source_contributions.neutralized_identifiers",
        ),
        run=_build,
        label="Bilan",
    ),
    Task(
        "attributes",
        reads=(
            "contribution_attributes_queue",
            "aligned_source_contributions",
            "source_contributions.is_corresponding",
            "source_contributions.perimeter_evidence",
            "source_contributions.roles",
            "source_contributions.author_position",
            "source_contributions.collective",
            "source_contributions.duplicate_of",
            "source_records.publication_id",
            "source_records.source_id",
            "contributions.id",
            "contributions.publication_id",
            "contributions.author_positions",
            "contributions.perimeter_evidence",
            "contributions.roles",
            "contributions.person_id",
            "contributions.resolution_mode",
        ),
        writes=(
            "contributions.author_positions",
            "contributions.perimeter_evidence",
            "contributions.roles",
            "contribution_attributes_queue",
            # Une contribution rattachée sans épinglage qui quitte le périmètre est marquée pour la redécision de sa personne.
            "contribution_resolution_queue",
        ),
        # Personnes des contributions, écrites par la phase `persons` ; contributions et alignements supprimés, enregistrements sources détachés par `finalize.purge_publications`.
        previous_run=(
            "contributions",
            "aligned_source_contributions",
            "source_records.publication_id",
        ),
        run=_attributes,
        label="Attributs des contributions",
    ),
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie les métriques du recalcul des contributions, avec le nombre de contributions aux attributs mis à jour."""
    metrics = by_task["build"]
    metrics.details["attributes_updated"] = by_task["attributes"].updated
    return metrics
