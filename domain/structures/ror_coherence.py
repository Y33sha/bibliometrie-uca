"""Cohérence entre `structure_tutelles` et les relations parent/enfant du ROR.

La comparaison se fait sur les clôtures transitives. Un parent ROR est couvert s'il est un ancêtre dans `structure_tutelles`. Une tutelle est couverte si son parent est un ancêtre dans le ROR.
"""

from collections import defaultdict
from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass

from domain.structures.identifiers import RorId


@dataclass(frozen=True, slots=True)
class TutelleCoherence:
    """Écarts entre les deux référentiels.

    - `absent_from_ror` : tutelles `(parent, enfant)` dont le parent est absent des ancêtres ROR de l'enfant.
    - `uncovered_ror_parents` : couples `(parent, enfant)` de structures dont le parent ROR est absent des ancêtres de l'enfant dans `structure_tutelles`.
    - `outside_parents` : couples `(structure, parent ROR)` dont le parent est absent de `structures`.
    - `outside_children` : couples `(structure, enfant ROR)` dont l'enfant est absent de `structures`.
    - `shared_ror_ids` : ROR attribués à plusieurs structures.
    """

    absent_from_ror: frozenset[tuple[int, int]]
    uncovered_ror_parents: frozenset[tuple[int, int]]
    outside_parents: frozenset[tuple[int, RorId]]
    outside_children: frozenset[tuple[int, RorId]]
    shared_ror_ids: frozenset[RorId]


def _parents_by_child[T: Hashable](edges: Iterable[tuple[T, T]]) -> dict[T, set[T]]:
    parents: dict[T, set[T]] = defaultdict(set)
    for parent, child in edges:
        parents[child].add(parent)
    return parents


def _ancestors[T: Hashable](node: T, parents: Mapping[T, set[T]]) -> set[T]:
    """Ancêtres stricts de `node`."""
    seen: set[T] = set()
    todo = list(parents.get(node, ()))
    while todo:
        current = todo.pop()
        if current not in seen:
            seen.add(current)
            todo.extend(parents.get(current, ()))
    return seen


def tutelle_coherence(
    *,
    structure_rors: Mapping[int, RorId],
    tutelles: Iterable[tuple[int, int]],
    ror_edges: Iterable[tuple[RorId, RorId]],
    scope: frozenset[int],
) -> TutelleCoherence:
    """Compare les tutelles aux relations du ROR.

    `structure_rors` associe chaque structure qui a un ROR à son ROR. `scope` restreint aux structures du périmètre la recherche de parents et d'enfants ROR absents de `structures`.
    """
    internal_parents = _parents_by_child(tutelles)
    ror_edges = list(ror_edges)
    ror_parents = _parents_by_child(ror_edges)
    ror_children: dict[RorId, set[RorId]] = defaultdict(set)
    for parent_ror, child_ror in ror_edges:
        ror_children[parent_ror].add(child_ror)

    structures_by_ror: dict[RorId, set[int]] = defaultdict(set)
    for structure_id, ror_id in structure_rors.items():
        structures_by_ror[ror_id].add(structure_id)

    absent_from_ror = frozenset(
        (parent, child)
        for child, parents in internal_parents.items()
        if child in structure_rors
        for parent in parents
        if parent in structure_rors
        and structure_rors[parent] not in _ancestors(structure_rors[child], ror_parents)
    )

    uncovered: set[tuple[int, int]] = set()
    outside_parents: set[tuple[int, RorId]] = set()
    for child, child_ror in structure_rors.items():
        internal_ancestors = _ancestors(child, internal_parents)
        for parent_ror in ror_parents.get(child_ror, ()):
            parents = structures_by_ror.get(parent_ror)
            if parents is None:
                if child in scope:
                    outside_parents.add((child, parent_ror))
            elif not parents & internal_ancestors:
                uncovered.update((parent, child) for parent in parents)

    outside_children = frozenset(
        (parent, child_ror)
        for parent in scope
        if parent in structure_rors
        for child_ror in ror_children.get(structure_rors[parent], ())
        if child_ror not in structures_by_ror
    )

    return TutelleCoherence(
        absent_from_ror=absent_from_ror,
        uncovered_ror_parents=frozenset(uncovered),
        outside_parents=frozenset(outside_parents),
        outside_children=outside_children,
        shared_ror_ids=frozenset(r for r, ids in structures_by_ror.items() if len(ids) > 1),
    )
