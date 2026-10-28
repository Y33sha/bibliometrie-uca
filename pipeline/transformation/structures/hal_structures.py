"""Référentiel des structures HAL (`hal_structures`, `hal_structure_relations`, `hal_structure_aliases`) : chargement en tête de la phase `affiliations`.

La tâche charge les structures citées par les contributions sources (`source_contribution_hal_structures`) ou comme parent (`hal_structures.parent_ids`), et absentes du référentiel. Un identifiant absent de `ref/structure` se cherche parmi les alias. Chaque lot lu est enregistré aussitôt : un run interrompu reprend au lot suivant. Les relations parent/enfant se reconstruisent ensuite depuis `parent_ids`. Quand une structure change de pays, les contributions sources qui la citent sont marquées pour la phase `countries`. En mode `full`, la tâche relit aussi les structures chargées depuis plus de `STALE_AFTER_DAYS` jours.
"""

import logging
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import batched
from typing import Protocol

from sqlalchemy import Connection, text

from domain.structures.hal_structures import HalStructure, parse_hal_structure
from domain.types import JsonValue
from infrastructure.db.queues import Queue, enqueue
from pipeline.http.circuit_breaker import SourceUnavailableError
from pipeline.ingestion.hal.api import HAL_STRUCTURES_BATCH
from pipeline.runtime.observability.log_format import LAST_BRANCH, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress, track_progress
from pipeline.runtime.observability.signals import signal_source_unavailable

STALE_AFTER_DAYS = 30


class HalStructuresSource(Protocol):
    def by_ids(self, ids: Collection[int]) -> Sequence[Mapping[str, JsonValue]]: ...

    def by_aliases(self, ids: Collection[int]) -> Sequence[Mapping[str, JsonValue]]: ...


class HalStructureStore:
    """Accès PostgreSQL du pipeline au référentiel des structures HAL."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def ids_to_fetch(self, *, refresh_stale: bool) -> set[int]:
        """Structures citées et absentes du référentiel, avec ses structures anciennes quand `refresh_stale` est vrai."""
        ids = set(
            self._conn.execute(
                text("""
                    SELECT hal_structure_id FROM source_contribution_hal_structures
                    UNION
                    SELECT unnest(parent_ids) FROM hal_structures
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
        """Écrit les structures et les alias. Un alias qui est lui-même une structure du référentiel est écarté. Marque pour le recalcul des pays les contributions sources qui citent une structure dont le pays change, ou un alias qui change de structure."""
        previous_countries: dict[int, str | None] = dict(
            self._conn.execute(
                text(
                    "SELECT hal_structure_id, country_code FROM hal_structures"
                    " WHERE hal_structure_id = ANY(:ids)"
                ),
                {"ids": [s.hal_structure_id for s in structures]},
            ).all()
        )
        previous_aliases: dict[int, int] = dict(
            self._conn.execute(
                text(
                    "SELECT alias_id, hal_structure_id FROM hal_structure_aliases"
                    " WHERE alias_id = ANY(:ids)"
                ),
                {"ids": list(aliases)},
            ).all()
        )
        if structures:
            self._conn.execute(
                text("""
                    INSERT INTO hal_structures (hal_structure_id, name, acronym, structure_type, country_code,
                                                status, ror_id, start_date, end_date, parent_ids, fetched_at)
                    VALUES (:hal_structure_id, :name, :acronym, :structure_type, :country_code,
                            CAST(:status AS hal_structure_status), :ror_id, :start_date, :end_date,
                            :parent_ids, now())
                    ON CONFLICT (hal_structure_id) DO UPDATE SET
                        name = excluded.name, acronym = excluded.acronym,
                        structure_type = excluded.structure_type, country_code = excluded.country_code,
                        status = excluded.status, ror_id = excluded.ror_id,
                        start_date = excluded.start_date, end_date = excluded.end_date,
                        parent_ids = excluded.parent_ids, fetched_at = excluded.fetched_at
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
                        "parent_ids": list(s.parent_ids),
                    }
                    for s in structures
                ],
            )
        if aliases:
            self._conn.execute(
                text("""
                    INSERT INTO hal_structure_aliases (alias_id, hal_structure_id)
                    SELECT :alias_id, :hal_structure_id
                    WHERE NOT EXISTS (SELECT 1 FROM hal_structures WHERE hal_structure_id = :alias_id)
                    ON CONFLICT (alias_id) DO UPDATE SET hal_structure_id = excluded.hal_structure_id
                """),
                [{"alias_id": a, "hal_structure_id": s} for a, s in aliases.items()],
            )
        self._mark_source_contributions(
            [
                s.hal_structure_id
                for s in structures
                if previous_countries.get(s.hal_structure_id) != s.country_code
            ],
            [a for a, s in aliases.items() if previous_aliases.get(a) != s],
        )

    def _mark_source_contributions(self, structure_ids: list[int], alias_ids: list[int]) -> None:
        """Marque pour le recalcul des pays les contributions sources qui citent une structure de `structure_ids`, directement ou par un alias, ou qui citent un alias de `alias_ids`."""
        if not structure_ids and not alias_ids:
            return
        enqueue(
            self._conn,
            Queue.SOURCE_CONTRIBUTION_COUNTRIES,
            """
            SELECT source_contribution_id FROM source_contribution_hal_structures
            WHERE hal_structure_id IN (
                SELECT unnest(CAST(:structures AS int[]) || CAST(:aliases AS int[]))
                UNION
                SELECT alias_id FROM hal_structure_aliases
                WHERE hal_structure_id = ANY(:structures)
            )
            """,
            {"structures": structure_ids, "aliases": alias_ids},
        )

    def rebuild_relations(self) -> None:
        """Reconstruit les relations parent/enfant depuis `parent_ids`, vers les parents présents dans le référentiel. Un parent alias est ramené à sa structure conservée."""
        self._conn.execute(
            text("""
                DELETE FROM hal_structure_relations;
                INSERT INTO hal_structure_relations (parent_id, child_id)
                SELECT DISTINCT p.hal_structure_id, h.hal_structure_id
                FROM hal_structures h
                CROSS JOIN LATERAL unnest(h.parent_ids) cited(parent_id)
                LEFT JOIN hal_structure_aliases al ON al.alias_id = cited.parent_id
                JOIN hal_structures p ON p.hal_structure_id = coalesce(al.hal_structure_id, cited.parent_id)
                WHERE p.hal_structure_id <> h.hal_structure_id;
            """)
        )


@dataclass
class HalStructuresLoad:
    """Identifiants cherchés dans `ref/structure`, parents compris, structures lues et identifiants introuvables."""

    requested: int = 0
    structures: int = 0
    not_found: set[int] = field(default_factory=set)


SaveBatch = Callable[[list[HalStructure], dict[int, int]], None]
"""Enregistre les structures et les alias `{alias: structure conservée}` d'un lot."""


def _parsed(docs: Iterable[Mapping[str, JsonValue]]) -> list[HalStructure]:
    return [s for doc in docs if (s := parse_hal_structure(doc)) is not None]


def fetch_hal_structures(
    ids: Collection[int],
    *,
    source: HalStructuresSource,
    store: HalStructureStore,
    save_batch: SaveBatch,
    progress: Progress | None = None,
) -> HalStructuresLoad:
    """Lit `ids` dans `ref/structure` par lots, résout les alias, puis lit les parents absents du référentiel, jusqu'à la racine. Chaque lot passe à `save_batch` dès sa lecture. `progress` compte les identifiants lus ; son total croît avec les parents à lire."""
    load = HalStructuresLoad()
    pending = set(ids)
    requested: set[int] = set()
    while pending:
        requested |= pending
        if progress is not None:
            progress.set_total(len(requested))
        parents: set[int] = set()
        for chunk in batched(sorted(pending), HAL_STRUCTURES_BATCH, strict=False):
            structures = {s.hal_structure_id: s for s in _parsed(source.by_ids(chunk))}
            missing = set(chunk) - structures.keys()
            aliases: dict[int, int] = {}
            if missing:
                for kept in _parsed(source.by_aliases(missing)):
                    structures[kept.hal_structure_id] = kept
                    for alias in missing & set(kept.alias_ids):
                        aliases[alias] = kept.hal_structure_id
                load.not_found |= missing - aliases.keys()
            for s in structures.values():
                for alias in s.alias_ids:
                    aliases.setdefault(alias, s.hal_structure_id)
                parents |= set(s.parent_ids)
            save_batch(list(structures.values()), aliases)
            load.structures += len(structures)
            if progress is not None:
                progress.advance(len(chunk))
        pending = parents - requested
        pending -= store.known_ids(pending)
    load.requested = len(requested)
    return load


def run_refresh_hal_structures(
    conn: Connection,
    *,
    source: HalStructuresSource,
    store: HalStructureStore,
    logger: logging.Logger,
    refresh_stale: bool,
) -> PhaseMetrics:
    """Charge les structures HAL citées et absentes du référentiel, relit les anciennes quand `refresh_stale` est vrai, puis reconstruit les relations. Chaque lot est validé dès son écriture."""
    metrics = PhaseMetrics()
    step(logger, "Référentiel des structures HAL")
    ids = store.ids_to_fetch(refresh_stale=refresh_stale)
    if not ids:
        logger.info("%sAucune structure à charger", LAST_BRANCH)
        return metrics

    def save_batch(structures: list[HalStructure], aliases: dict[int, int]) -> None:
        store.save(structures, aliases)
        conn.commit()

    try:
        with track_progress(len(ids), f"{LAST_BRANCH}HAL", logger) as progress:
            load = fetch_hal_structures(
                ids, source=source, store=store, save_batch=save_batch, progress=progress
            )
    except SourceUnavailableError:
        conn.rollback()
        store.rebuild_relations()
        conn.commit()
        signal_source_unavailable(metrics, "hal", logger=logger, phase="affiliations")
        metrics.report = "référentiel HAL inaccessible, chargement repris au prochain run"
        return metrics
    store.rebuild_relations()
    conn.commit()
    metrics.add(seen=len(ids), updated=load.structures)
    metrics.details["hal_structures"] = {
        "requested": load.requested,
        "loaded": load.structures,
        "not_found": len(load.not_found),
    }
    logger.info(
        "%s%d structures cherchées : %d trouvées, %d introuvables",
        LAST_BRANCH,
        load.requested,
        load.requested - len(load.not_found),
        len(load.not_found),
    )
    return metrics
