"""Phase `author_grouping` : groupes des signatures d'un même auteur dans chaque publication (`source_authorship_groups`, `grouped_source_authorships`).

Les publications marquées `authorships_dirty` se recalculent entièrement, par lots ; les publications d'un lot se répartissent entre des processus, un par processeur disponible (`available_cpus`). Les doublons d'auteur d'une notice (`domain.publications.list_copies`) reçoivent `duplicate_of` et restent hors des groupes. Les autres signatures, tous rôles réunis, s'alignent par la règle de noms, le filtre d'ordre, l'ordre dans les trous et le modèle du résidu (`domain.publications.author_grouping`). Chaque groupe reprend l'identifiant du groupe en base avec lequel il partage le plus de signatures.

Nœud `author_grouping.build`.
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
    Signature,
    align_publication,
    plan_group_ids,
    with_known_first_name,
)
from domain.publications.list_copies import copied_signatures
from pipeline.node_runner import NodePhase
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.cpu import available_cpus
from pipeline.runtime.observability.libelles import DERNIERE_BRANCHE, accord, etape, rien_a_faire
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import attente, progression
from pipeline.transformation.publications.author_grouping.queries import (
    AuthorGroupingQueries,
    GroupRow,
    MembershipRow,
    SignatureRow,
)
from pipeline.transformation.publications.author_grouping.residual_weights import (
    RESIDUAL_WEIGHTS,
)

# Plafonds d'un lot de publications : nombre de publications, nombre de signatures d'auteur chargées en mémoire.
BATCH_SIZE = 1000
BATCH_SIGNATURES = 200_000
_MODEL = ResidualModel(RESIDUAL_WEIGHTS)
# Source dont la notice passe après les autres à longueur de liste égale : elle fonde un groupe seulement à défaut d'une autre.
DEFERRED_SOURCE = "scanr"


def publication_batches(publications: Sequence[tuple[int, int]]) -> list[list[int]]:
    """Lots de publications, dans l'ordre : un lot se ferme à `BATCH_SIZE` publications ou dès qu'il atteint `BATCH_SIGNATURES` signatures. `publications` : (publication, nombre de signatures)."""
    batches: list[list[int]] = []
    batch: list[int] = []
    signatures = 0
    for publication_id, count in publications:
        batch.append(publication_id)
        signatures += count
        if len(batch) >= BATCH_SIZE or signatures >= BATCH_SIGNATURES:
            batches.append(batch)
            batch, signatures = [], 0
    if batch:
        batches.append(batch)
    return batches


def assign(matrix: Sequence[Sequence[float]]) -> Iterable[tuple[int, int]]:
    """Affectation de gain maximal (algorithme hongrois)."""
    rows, cols = linear_sum_assignment([[-value for value in row] for row in matrix])
    return zip(rows.tolist(), cols.tolist(), strict=True)


def notices_of(rows: Sequence[SignatureRow]) -> dict[int, list[Signature]]:
    """Signatures d'une publication par notice, tous rôles réunis. Une signature réduite à des initiales prend le prénom de la personne à laquelle un humain a rattaché son identifiant (`with_known_first_name`)."""
    notices: dict[int, list[Signature]] = {}
    for row in rows:
        first_name = with_known_first_name(row.first_name, row.known_first_name)
        notices.setdefault(row.notice, []).append(
            Signature(
                row.id, row.notice, row.position, row.last_name, first_name, row.orcid, row.idref
            )
        )
    return notices


def deferred_notices(rows: Sequence[SignatureRow]) -> set[int]:
    """Notices de `DEFERRED_SOURCE` parmi les signatures d'une publication."""
    return {row.notice for row in rows if row.source == DEFERRED_SOURCE}


def group_publication(rows: Sequence[SignatureRow]) -> tuple[list[Group], dict[int, int]]:
    """Groupes des signatures d'une publication et doublons d'auteur (doublon → première occurrence de son nom), parmi les signatures qui ont une position. Les doublons restent hors des groupes."""
    notices = notices_of(rows)
    copies: dict[int, int] = {}
    for signatures in notices.values():
        copies |= copied_signatures(signatures)
    kept = {n: [s for s in sigs if s.id not in copies] for n, sigs in notices.items()}
    groups = align_publication(kept, model=_MODEL, assign=assign, deferred=deferred_notices(rows))
    return groups, copies


def _same_membership(stored: MembershipRow | None, planned: MembershipRow) -> bool:
    """L'appartenance en base vaut l'appartenance calculée. Le score et la marge sont comparés à la précision de leur colonne (`real`)."""
    if stored is None:
        return False

    def close(a: float | None, b: float | None) -> bool:
        return a is None if b is None else a is not None and math.isclose(a, b, rel_tol=1e-6)

    return (
        (stored.group, stored.notice, stored.method)
        == (planned.group, planned.notice, planned.method)
        and close(stored.score, planned.score)
        and close(stored.margin, planned.margin)
    )


def membership_changes(
    stored: Mapping[int, MembershipRow], planned: Sequence[MembershipRow]
) -> tuple[list[int], list[MembershipRow]]:
    """Signatures dont l'appartenance en base disparaît ou change, et appartenances à insérer. Une appartenance inchangée reste en place."""
    inserted = [m for m in planned if not _same_membership(stored.get(m.signature), m)]
    kept = {m.signature for m in planned}
    removed = [s for s in stored if s not in kept] + [m.signature for m in inserted]
    return removed, inserted


# Signature (champs de `SignatureRow` dans l'ordre), appartenance (signature, notice, méthode, score, marge) et groupe (signature de référence, appartenances), en tuples : la forme la moins coûteuse à faire passer d'un processus à l'autre.
type SignatureTuple = tuple[int, int, str, int, int | None, str, str, str, str, str]
type MemberTuple = tuple[int, int, str, float | None, float | None]
type GroupTuple = tuple[int, list[MemberTuple]]
type Aligned = tuple[list[GroupTuple], dict[int, int]]

_SIGNATURE_FIELDS = attrgetter(*(f.name for f in fields(SignatureRow)))


def align_rows(rows: Sequence[SignatureTuple]) -> Aligned:
    """`group_publication` sur les signatures d'une publication en tuples, résultat en tuples."""
    groups, copies = group_publication([SignatureRow(*row) for row in rows])
    return [
        (
            g.reference.id,
            [(m.signature, m.notice, str(m.method), m.score, m.margin) for m in g.members],
        )
        for g in groups
    ], copies


type Mapper = Callable[
    [Callable[[Sequence[SignatureTuple]], Aligned], Sequence[Sequence[SignatureTuple]]],
    Iterator[Aligned],
]
"""Applique `align_rows` aux signatures de chaque publication et rend les résultats dans l'ordre : `map`, ou un pool de processus."""


def pool_mapper(pool: ProcessPoolExecutor, workers: int) -> Mapper:
    """`Mapper` qui répartit les publications d'un lot entre les `workers` processus de `pool`, par paquets de taille adaptée au lot."""

    def mapper(
        fn: Callable[[Sequence[SignatureTuple]], Aligned],
        items: Sequence[Sequence[SignatureTuple]],
    ) -> Iterator[Aligned]:
        return pool.map(fn, items, chunksize=max(1, len(items) // (4 * workers)))

    return mapper


def _plan_batch(
    queries: AuthorGroupingQueries,
    conn: Connection,
    publication_ids: Sequence[int],
    methods: Counter[str],
    on_publication: Callable[[], None],
    mapper: Mapper,
) -> tuple[list[GroupRow], list[int], list[MembershipRow], list[int], dict[int, int]]:
    """Plan d'écriture d'un lot de publications : groupes, signatures dont l'appartenance est à supprimer, appartenances à insérer, groupes en base sans correspondant, doublons d'auteur. `on_publication` est appelé après chaque publication calculée."""
    rows_by_publication: dict[int, list[SignatureTuple]] = {}
    positions: dict[int, int | None] = {}
    for row in queries.fetch_signatures(conn, publication_ids):
        rows_by_publication.setdefault(row.publication_id, []).append(_SIGNATURE_FIELDS(row))
        positions[row.id] = row.position
    existing, stored = queries.fetch_groups(conn, publication_ids)
    planned: list[tuple[int, GroupTuple, int | None]] = []
    unmatched: list[int] = []
    copies: dict[int, int] = {}
    results = mapper(align_rows, [rows_by_publication.get(p, []) for p in publication_ids])
    for publication_id, (groups, publication_copies) in zip(publication_ids, results, strict=True):
        copies |= publication_copies
        old = {gid: frozenset(sigs) for gid, sigs in existing.get(publication_id, {}).items()}
        plan = plan_group_ids(old, [frozenset(m[0] for m in members) for _, members in groups])
        planned += [(publication_id, g, gid) for g, gid in zip(groups, plan, strict=True)]
        unmatched += sorted(set(old) - {gid for gid in plan if gid is not None})
        on_publication()
    fresh = iter(queries.group_ids(conn, sum(1 for *_, gid in planned if gid is None)))
    group_rows: list[GroupRow] = []
    memberships: list[MembershipRow] = []
    for publication_id, (reference, members), gid in planned:
        existing_id = gid is not None
        group_id = gid if gid is not None else next(fresh)
        group_rows.append(GroupRow(group_id, publication_id, positions[reference], existing_id))
        for signature, notice, method, score, margin in members:
            methods[method] += 1
            memberships.append(MembershipRow(signature, group_id, notice, method, score, margin))
    removed, inserted = membership_changes(stored, memberships)
    return group_rows, removed, inserted, unmatched, copies


def regroup(
    conn: Connection,
    queries: AuthorGroupingQueries,
    publication_ids: Sequence[int],
    methods: Counter[str] | None = None,
    on_publication: Callable[[], None] = lambda: None,
    mapper: Mapper = map,
) -> int:
    """Recalcule et écrit les groupes et les doublons d'auteur de ces publications, sans commit. Rend le nombre de groupes écrits ; `methods` compte les appartenances par origine."""
    groups, removed, inserted, unmatched, copies = _plan_batch(
        queries,
        conn,
        publication_ids,
        methods if methods is not None else Counter(),
        on_publication,
        mapper,
    )
    queries.write(conn, publication_ids, groups, removed, inserted, unmatched, copies)
    return len(groups)


def build_groups(
    conn: Connection, queries: AuthorGroupingQueries, logger: logging.Logger
) -> PhaseMetrics:
    """Supprime les groupes des publications supprimées, puis recalcule les groupes des publications marquées, lot par lot, avec un commit par lot. Rafraîchit ensuite le recouvrement des listes d'auteurs."""
    orphans = queries.delete_orphan_groups(conn)
    conn.commit()
    if orphans:
        etape(
            logger,
            "%s : leur publication n'existe plus",
            accord(orphans, "groupe supprimé", "groupes supprimés"),
        )
    dirty = queries.fetch_dirty_publications(conn)
    publication_ids = [publication_id for publication_id, _ in dirty]
    etape(logger, "auteurs à aligner dans %s", accord(len(publication_ids), "publication"))
    if not publication_ids:
        if orphans:
            queries.refresh_alignment(conn)
            conn.commit()
        rien_a_faire(logger)
        return PhaseMetrics()
    metrics = PhaseMetrics(seen=len(publication_ids))
    methods: Counter[str] = Counter()
    group_count = 0
    workers = min(available_cpus(), len(publication_ids))
    with (
        ProcessPoolExecutor(max_workers=workers) if workers > 1 else nullcontext() as pool,
        progression(len(publication_ids), DERNIERE_BRANCHE.rstrip(), logger) as avancement,
    ):
        mapper: Mapper = pool_mapper(pool, workers) if pool is not None else map
        for batch in publication_batches(dirty):
            group_count += regroup(conn, queries, batch, methods, avancement.avance, mapper)
            conn.commit()
    etape(logger, "Recouvrement des listes d'auteurs")
    t0 = time.perf_counter()
    with attente(DERNIERE_BRANCHE, logger) as ligne:
        queries.refresh_alignment(conn)
        conn.commit()
        ligne.conclut(f"{DERNIERE_BRANCHE}Terminé en {time.perf_counter() - t0:.1f}s")
    metrics.add(updated=len(publication_ids))
    metrics.details["summary"] = {
        "publications": len(publication_ids),
        "groups": group_count,
        **{str(method): count for method, count in methods.items()},
    }
    metrics.resume = (
        f"{accord(len(publication_ids), 'publication')}, {accord(group_count, 'groupe')}"
    )
    return metrics


@dataclass(frozen=True)
class AuthorGroupingPhase:
    queries: AuthorGroupingQueries

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        with ctx.open_tx() as conn:
            return build_groups(conn, self.queries, ctx.logger)


def build() -> Phase:
    """Groupe les signatures d'un même auteur dans les publications marquées."""
    return NodePhase("author_grouping.build", AuthorGroupingPhase(AuthorGroupingQueries()))
