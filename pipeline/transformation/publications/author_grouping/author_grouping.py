"""Phase `author_grouping` : groupes des signatures d'un même auteur dans chaque publication (`source_authorship_groups`, `grouped_source_authorships`).

Les publications marquées `authorships_dirty` se recalculent entièrement, par lots. Les auteurs s'alignent par la règle de noms, le filtre d'ordre, l'ordre dans les trous et le modèle du résidu (`domain.publications.author_grouping`). Les signatures d'un autre rôle (jury, direction de thèse, édition) s'alignent rôle par rôle, par la seule règle de noms. Chaque groupe reprend l'identifiant du groupe en base avec lequel il partage le plus de signatures.

Nœud `author_grouping.build`.
"""

import logging
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from scipy.optimize import linear_sum_assignment
from sqlalchemy import Connection

from domain.publications.author_grouping import (
    Group,
    ResidualModel,
    Signature,
    align_publication,
    plan_group_ids,
)
from pipeline.node_runner import NodePhase
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.libelles import DERNIERE_BRANCHE, accord, etape, rien_a_faire
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import progression
from pipeline.transformation.publications.author_grouping.queries import (
    AuthorGroupingQueries,
    GroupRow,
    MembershipRow,
    SignatureRow,
)
from pipeline.transformation.publications.author_grouping.residual_weights import (
    RESIDUAL_WEIGHTS,
)

BATCH_SIZE = 1000
_MODEL = ResidualModel(RESIDUAL_WEIGHTS)
AUTHOR = "author"
# Source dont la notice passe après les autres à longueur de liste égale : elle fonde un groupe seulement à défaut d'une autre.
DEFERRED_SOURCE = "scanr"


def assign(matrix: Sequence[Sequence[float]]) -> Iterable[tuple[int, int]]:
    """Affectation de gain maximal (algorithme hongrois)."""
    rows, cols = linear_sum_assignment([[-value for value in row] for row in matrix])
    return zip(rows.tolist(), cols.tolist(), strict=True)


def _role_class(roles: list[str] | None) -> str:
    """Classe d'alignement d'une signature : les auteurs ensemble, les autres rôles chacun à part."""
    roles = roles or [AUTHOR]
    return AUTHOR if AUTHOR in roles else ",".join(sorted(roles))


def notices_by_role(rows: Sequence[SignatureRow]) -> dict[str, dict[int, list[Signature]]]:
    """Signatures d'une publication par classe de rôle, puis par notice.

    Une signature sans position prend la position 0 pour l'alignement, qui la range alors par identifiant.
    """
    by_class: dict[str, dict[int, list[Signature]]] = {}
    for row in rows:
        notices = by_class.setdefault(_role_class(row.roles), {})
        position = row.position if row.position is not None else 0
        notices.setdefault(row.notice, []).append(
            Signature(
                row.id, row.notice, position, row.last_name, row.first_name, row.orcid, row.idref
            )
        )
    return by_class


def deferred_notices(rows: Sequence[SignatureRow]) -> set[int]:
    """Notices de `DEFERRED_SOURCE` parmi les signatures d'une publication."""
    return {row.notice for row in rows if row.source == DEFERRED_SOURCE}


def group_publication(rows: Sequence[SignatureRow]) -> list[Group]:
    """Groupes des signatures d'une publication, classe de rôle par classe de rôle."""
    deferred = deferred_notices(rows)
    groups: list[Group] = []
    for role_class, notices in sorted(notices_by_role(rows).items()):
        if role_class == AUTHOR:
            groups += align_publication(notices, model=_MODEL, assign=assign, deferred=deferred)
        else:
            groups += align_publication(notices, ordered=False, deferred=deferred)
    return groups


def _plan_batch(
    queries: AuthorGroupingQueries,
    conn: Connection,
    publication_ids: Sequence[int],
    methods: Counter[str],
    on_publication: Callable[[], None],
) -> tuple[list[GroupRow], list[MembershipRow], list[int]]:
    """Groupes et appartenances à écrire pour un lot de publications, et groupes en base sans correspondant. `on_publication` est appelé après chaque publication calculée."""
    rows_by_publication: dict[int, list[SignatureRow]] = {}
    positions: dict[int, int | None] = {}
    for row in queries.fetch_signatures(conn, publication_ids):
        rows_by_publication.setdefault(row.publication_id, []).append(row)
        positions[row.id] = row.position
    existing = queries.fetch_groups(conn, publication_ids)
    planned: list[tuple[int, Group, int | None]] = []
    unmatched: list[int] = []
    for publication_id in publication_ids:
        groups = group_publication(rows_by_publication.get(publication_id, []))
        old = {gid: frozenset(sigs) for gid, sigs in existing.get(publication_id, {}).items()}
        plan = plan_group_ids(old, [frozenset(m.signature for m in g.members) for g in groups])
        planned += [(publication_id, g, gid) for g, gid in zip(groups, plan, strict=True)]
        unmatched += sorted(set(old) - {gid for gid in plan if gid is not None})
        on_publication()
    fresh = iter(queries.group_ids(conn, sum(1 for *_, gid in planned if gid is None)))
    group_rows: list[GroupRow] = []
    memberships: list[MembershipRow] = []
    for publication_id, group, gid in planned:
        existing_id = gid is not None
        group_id = gid if gid is not None else next(fresh)
        group_rows.append(
            GroupRow(group_id, publication_id, positions[group.reference.id], existing_id)
        )
        for m in group.members:
            methods[m.method] += 1
            memberships.append(
                MembershipRow(m.signature, group_id, m.notice, str(m.method), m.score, m.margin)
            )
    return group_rows, memberships, unmatched


def regroup(
    conn: Connection,
    queries: AuthorGroupingQueries,
    publication_ids: Sequence[int],
    methods: Counter[str] | None = None,
    on_publication: Callable[[], None] = lambda: None,
) -> int:
    """Recalcule et écrit les groupes de ces publications, sans commit. Rend le nombre de groupes écrits ; `methods` compte les appartenances par origine."""
    groups, memberships, unmatched = _plan_batch(
        queries,
        conn,
        publication_ids,
        methods if methods is not None else Counter(),
        on_publication,
    )
    queries.write(conn, publication_ids, groups, memberships, unmatched)
    return len(groups)


def build_groups(
    conn: Connection, queries: AuthorGroupingQueries, logger: logging.Logger
) -> PhaseMetrics:
    """Supprime les groupes des publications supprimées, puis recalcule les groupes des publications marquées, lot par lot, avec un commit par lot."""
    orphans = queries.delete_orphan_groups(conn)
    conn.commit()
    etape(logger, "%s de publications supprimées retirés", accord(orphans, "groupe"))
    publication_ids = queries.fetch_dirty_publication_ids(conn)
    etape(logger, "%s à regrouper", accord(len(publication_ids), "publication"))
    if not publication_ids:
        rien_a_faire(logger)
        return PhaseMetrics()
    metrics = PhaseMetrics(seen=len(publication_ids))
    methods: Counter[str] = Counter()
    group_count = 0
    with progression(len(publication_ids), DERNIERE_BRANCHE.rstrip(), logger) as avancement:
        for start in range(0, len(publication_ids), BATCH_SIZE):
            batch = publication_ids[start : start + BATCH_SIZE]
            group_count += regroup(conn, queries, batch, methods, avancement.avance)
            conn.commit()
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
