"""Référentiel des structures HAL (`hal_structures`, `hal_structure_relations`, `hal_structure_aliases`) : chargement en tête de la phase `affiliations`.

Le nœud charge les structures citées par les signatures (`source_authorship_hal_structures`) ou par les structures internes (`structures.api_ids->'hal'`) et absentes du référentiel, puis leurs parents, jusqu'à la racine. Un identifiant absent de `ref/structure` se cherche parmi les alias. En mode `full`, le nœud relit aussi les structures chargées depuis plus de `STALE_AFTER_DAYS` jours.
"""

import logging
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import batched
from typing import Protocol

from sqlalchemy import Connection, text

from domain.structures.hal_structures import HalStructure, parse_hal_structure
from domain.types import JsonValue
from pipeline.ingestion.hal.structures import HAL_STRUCTURES_BATCH
from pipeline.ingestion.http.circuit_breaker import SourceUnavailableError
from pipeline.runtime.observability.libelles import DERNIERE_BRANCHE, etape
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import Progression, progression
from pipeline.runtime.observability.signals import signal_source_unavailable

STALE_AFTER_DAYS = 30


class HalStructuresSource(Protocol):
    def by_ids(self, ids: Collection[int]) -> Sequence[Mapping[str, JsonValue]]: ...

    def by_aliases(self, ids: Collection[int]) -> Sequence[Mapping[str, JsonValue]]: ...


class HalStructuresQueries:
    """Accès PostgreSQL du pipeline au référentiel des structures HAL."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def ids_to_fetch(self, *, refresh_stale: bool) -> set[int]:
        """Structures citées et absentes du référentiel, avec ses structures anciennes quand `refresh_stale` est vrai."""
        ids = set(
            self._conn.execute(
                text("""
                    SELECT hal_structure_id FROM source_authorship_hal_structures
                    UNION
                    SELECT h.value::int
                    FROM structures s
                    CROSS JOIN LATERAL jsonb_array_elements_text(s.api_ids -> 'hal') h(value)
                    WHERE s.api_ids ? 'hal' AND h.value ~ '^[0-9]+$'
                    EXCEPT
                    SELECT hal_structure_id FROM hal_structures
                    EXCEPT
                    SELECT alias_id FROM hal_structure_aliases
                """)
            ).scalars()
        )
        if refresh_stale:
            ids |= set(
                self._conn.execute(
                    text(
                        "SELECT hal_structure_id FROM hal_structures"
                        " WHERE fetched_at < now() - make_interval(days => :days)"
                    ),
                    {"days": STALE_AFTER_DAYS},
                ).scalars()
            )
        return ids

    def known_ids(self, ids: Iterable[int]) -> set[int]:
        """Identifiants de `ids` déjà présents dans le référentiel, comme structure ou comme alias."""
        return set(
            self._conn.execute(
                text("""
                    SELECT hal_structure_id FROM hal_structures WHERE hal_structure_id = ANY(:ids)
                    UNION
                    SELECT alias_id FROM hal_structure_aliases WHERE alias_id = ANY(:ids)
                """),
                {"ids": list(ids)},
            ).scalars()
        )

    def save(self, structures: Collection[HalStructure], aliases: Mapping[int, int]) -> None:
        """Écrit les structures, les alias, puis les relations des structures écrites vers leurs parents présents dans le référentiel, un parent alias étant ramené à sa structure conservée. Les relations d'une structure écrite sont celles de sa dernière lecture."""
        if structures:
            self._conn.execute(
                text("""
                    INSERT INTO hal_structures (hal_structure_id, name, acronym, structure_type, country_code,
                                                status, ror_id, start_date, end_date, fetched_at)
                    VALUES (:hal_structure_id, :name, :acronym, :structure_type, :country_code,
                            CAST(:status AS hal_structure_status), :ror_id, :start_date, :end_date, now())
                    ON CONFLICT (hal_structure_id) DO UPDATE SET
                        name = excluded.name, acronym = excluded.acronym,
                        structure_type = excluded.structure_type, country_code = excluded.country_code,
                        status = excluded.status, ror_id = excluded.ror_id,
                        start_date = excluded.start_date, end_date = excluded.end_date,
                        fetched_at = excluded.fetched_at
                """),
                [
                    {
                        "hal_structure_id": s.hal_structure_id,
                        "name": s.name,
                        "acronym": s.acronym,
                        "structure_type": s.structure_type,
                        "country_code": s.country_code,
                        "status": s.status.value,
                        "ror_id": s.ror_id.value if s.ror_id else None,
                        "start_date": s.start_date,
                        "end_date": s.end_date,
                    }
                    for s in structures
                ],
            )
        if aliases:
            self._conn.execute(
                text("""
                    INSERT INTO hal_structure_aliases (alias_id, hal_structure_id)
                    VALUES (:alias_id, :hal_structure_id)
                    ON CONFLICT (alias_id) DO UPDATE SET hal_structure_id = excluded.hal_structure_id
                """),
                [{"alias_id": a, "hal_structure_id": s} for a, s in aliases.items()],
            )
        if structures:
            self._conn.execute(
                text("DELETE FROM hal_structure_relations WHERE child_id = ANY(:ids)"),
                {"ids": [s.hal_structure_id for s in structures]},
            )
            relations = [
                {"parent_id": parent, "child_id": s.hal_structure_id}
                for s in structures
                for parent in s.parent_ids
            ]
            if relations:
                self._conn.execute(
                    text("""
                        INSERT INTO hal_structure_relations (parent_id, child_id)
                        SELECT h.hal_structure_id, :child_id
                        FROM hal_structures h
                        WHERE h.hal_structure_id = coalesce(
                            (SELECT hal_structure_id FROM hal_structure_aliases WHERE alias_id = :parent_id),
                            :parent_id
                        ) AND h.hal_structure_id <> :child_id
                        ON CONFLICT DO NOTHING
                    """),
                    relations,
                )


@dataclass
class HalStructuresLoad:
    """Structures et alias lus dans `ref/structure`, et identifiants introuvables."""

    structures: dict[int, HalStructure] = field(default_factory=dict)
    aliases: dict[int, int] = field(default_factory=dict)
    not_found: set[int] = field(default_factory=set)


def _parsed(docs: Iterable[Mapping[str, JsonValue]]) -> list[HalStructure]:
    return [s for doc in docs if (s := parse_hal_structure(doc)) is not None]


def fetch_hal_structures(
    ids: Collection[int],
    *,
    source: HalStructuresSource,
    queries: HalStructuresQueries,
    avancement: Progression | None = None,
) -> HalStructuresLoad:
    """Lit `ids` dans `ref/structure`, résout les alias, puis lit les parents absents du référentiel, jusqu'à la racine. `avancement` compte les identifiants lus ; son total croît avec les parents à lire."""
    load = HalStructuresLoad()
    pending = set(ids)
    requested = 0
    while pending:
        requested += len(pending)
        if avancement is not None:
            avancement.fixer_total(requested)
        for chunk in batched(sorted(pending), HAL_STRUCTURES_BATCH):
            found = {s.hal_structure_id: s for s in _parsed(source.by_ids(chunk))}
            load.structures.update(found)
            missing = set(chunk) - found.keys()
            if missing:
                for kept in _parsed(source.by_aliases(missing)):
                    load.structures[kept.hal_structure_id] = kept
                    for alias in missing & set(kept.alias_ids):
                        load.aliases[alias] = kept.hal_structure_id
                load.not_found |= missing - load.aliases.keys()
            if avancement is not None:
                avancement.avance(len(chunk))
        parents = {p for s in load.structures.values() for p in s.parent_ids}
        pending = parents - load.structures.keys() - load.not_found
        pending -= queries.known_ids(pending)
    for s in load.structures.values():
        for alias in s.alias_ids:
            load.aliases.setdefault(alias, s.hal_structure_id)
    for alias in list(load.aliases):
        if alias in load.structures:
            del load.aliases[alias]
    return load


def run_refresh_hal_structures(
    conn: Connection,
    *,
    source: HalStructuresSource,
    queries: HalStructuresQueries,
    logger: logging.Logger,
    refresh_stale: bool,
) -> PhaseMetrics:
    """Charge les structures HAL citées et absentes du référentiel, et relit les anciennes quand `refresh_stale` est vrai."""
    metrics = PhaseMetrics()
    etape(logger, "Référentiel des structures HAL")
    ids = queries.ids_to_fetch(refresh_stale=refresh_stale)
    if not ids:
        logger.info("%sAucune structure à charger", DERNIERE_BRANCHE)
        return metrics
    try:
        with progression(len(ids), f"{DERNIERE_BRANCHE}HAL", logger) as avancement:
            load = fetch_hal_structures(ids, source=source, queries=queries, avancement=avancement)
    except SourceUnavailableError:
        conn.rollback()
        signal_source_unavailable(metrics, "hal", logger=logger, phase="affiliations")
        metrics.resume = "référentiel HAL inaccessible, chargement repris au prochain run"
        return metrics
    queries.save(list(load.structures.values()), load.aliases)
    conn.commit()
    metrics.add(total=len(ids), updated=len(load.structures))
    metrics.details["hal_structures"] = {
        "requested": len(ids),
        "loaded": len(load.structures),
        "aliases": len(load.aliases),
        "not_found": len(load.not_found),
    }
    logger.info(
        "%s%d structures chargées, %d alias, %d introuvables",
        DERNIERE_BRANCHE,
        len(load.structures),
        len(load.aliases),
        len(load.not_found),
    )
    return metrics
