"""Composition des lots de personnes du moissonnage par personne.

Un document signé par plusieurs personnes d'un même lot est téléchargé une fois. Les lots réunissent donc les personnes qui copublient, d'après les publications en base sur les années du moissonnage.

Un lot part de la personne restante la plus productive. Il s'agrandit de la personne qui partage le plus de publications avec lui, puis, à égalité, de celle qui lui en ajoute le moins. Sans personne qui partage une publication avec le lot, il s'agrandit de la personne suivante dans l'ordre de départ : nombre de publications décroissant, unité actuelle, identifiant.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping

from sqlalchemy import Connection, text

from infrastructure.read_models.sql_fragments import current_unit


def read_batching_inputs(
    conn: Connection, person_ids: Collection[int], years: tuple[int, int]
) -> tuple[dict[int, frozenset[int]], dict[int, str | None]]:
    """Renvoie, par personne de `person_ids`, ses publications parues entre les deux années de `years` et son unité actuelle."""
    rows = conn.execute(
        text(f"""
            SELECT p.id AS person_id, {current_unit("p")} AS unit,
                   ARRAY(
                       SELECT DISTINCT c.publication_id
                       FROM contributions c
                       JOIN publications pub ON pub.id = c.publication_id
                       WHERE c.person_id = p.id
                         AND pub.publication_year BETWEEN :first_year AND :last_year
                   ) AS publication_ids
            FROM persons p
            WHERE p.id = ANY(:ids)
        """),
        {"ids": list(person_ids), "first_year": years[0], "last_year": years[1]},
    )
    publications: dict[int, frozenset[int]] = {}
    units: dict[int, str | None] = {}
    for r in rows:
        publications[r.person_id] = frozenset(r.publication_ids)
        units[r.person_id] = r.unit
    return publications, units


def compose_batches(
    person_ids: Collection[int],
    publications: Mapping[int, frozenset[int]],
    units: Mapping[int, str | None],
    size: int,
) -> list[list[int]]:
    """Répartit `person_ids` en lots d'au plus `size` personnes, réunies par copublication. Une personne absente de `publications` ou de `units` compte sans publication ou sans unité."""
    empty: frozenset[int] = frozenset()
    order = sorted(
        person_ids,
        key=lambda p: (
            -len(publications.get(p, empty)),
            units.get(p) is None,
            units.get(p) or "",
            p,
        ),
    )
    rank = {p: i for i, p in enumerate(order)}
    authors: dict[int, list[int]] = defaultdict(list)
    for p in order:
        for publication in publications.get(p, empty):
            authors[publication].append(p)

    placed: set[int] = set()
    next_in_order = 0
    batches: list[list[int]] = []
    while len(placed) < len(order):
        batch: list[int] = []
        covered: set[int] = set()
        # Nombre de publications partagées avec le lot, par personne restante.
        shared: dict[int, int] = {}
        while len(batch) < size and len(placed) < len(order):
            if shared:
                person = max(
                    shared,
                    key=lambda q: (
                        shared[q],
                        shared[q] - len(publications.get(q, empty)),
                        -rank[q],
                    ),
                )
                del shared[person]
            else:
                while order[next_in_order] in placed:
                    next_in_order += 1
                person = order[next_in_order]
            placed.add(person)
            batch.append(person)
            for publication in publications.get(person, empty) - covered:
                covered.add(publication)
                for coauthor in authors[publication]:
                    if coauthor not in placed:
                        shared[coauthor] = shared.get(coauthor, 0) + 1
        batches.append(batch)
    return batches
