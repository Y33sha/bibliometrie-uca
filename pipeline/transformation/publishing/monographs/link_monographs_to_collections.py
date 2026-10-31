"""Sous-étape de la phase `publishing` : rattachement de chaque monographie à sa collection.

Les monographies sans collection à ISSN se regroupent en séries (`group_series`, `domain/serials/series.py`) : même clé de série, même éditeur, au moins deux volumes. Chaque série a son entrée dans `serials`, la revue sans ISSN de son titre et de son éditeur (`serial_for_title`), typée série d'actes ou collection de livres selon ses volumes. `choose_monograph_serial` (`domain/monographs/collection.py`) choisit ensuite l'entrée de chaque monographie : sa collection à ISSN, à défaut sa série sans ISSN, à défaut le volume lui-même, à défaut aucune. Une monographie en conflit reste en l'état, signalée. Le calcul se refait à chaque run, d'après les enregistrements sources.
"""

import logging
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.monographs.collection import MonographSerialChoice, choose_monograph_serial
from domain.normalize import normalize_text
from domain.serials.serial import SerialType
from domain.serials.series import VolumeTitle, group_series
from infrastructure.sql_fragments import has_active_issn
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.serials.store import SerialStore

LABEL = "Rattachement aux collections"
"""Libellé de la sous-étape dans le journal de la phase."""


class MonographSerialCandidates(NamedTuple):
    """Une monographie et les entrées de `serials` de ses enregistrements sources, avec ou sans ISSN actif."""

    monograph_id: int
    title: str
    publisher_id: int | None
    proceedings: bool
    serial_id: int | None
    with_issn: tuple[int, ...]
    without_issn: tuple[int, ...]


_SERIAL_CANDIDATES = text(f"""
    WITH entrees AS (
        SELECT DISTINCT s.monograph_id, s.serial_id,
               {has_active_issn("s.serial_id")} AS a_issn
        FROM source_records s
        WHERE s.monograph_id IS NOT NULL
    )
    SELECT m.id, m.title, m.publisher_id, m.proceedings, m.serial_id,
           coalesce(array_agg(e.serial_id ORDER BY e.serial_id) FILTER (
               WHERE e.serial_id IS NOT NULL AND e.a_issn
           ), '{{}}') AS with_issn,
           coalesce(array_agg(e.serial_id ORDER BY e.serial_id) FILTER (
               WHERE e.serial_id IS NOT NULL AND NOT e.a_issn
           ), '{{}}') AS without_issn
    FROM monographs m
    JOIN entrees e ON e.monograph_id = m.id
    GROUP BY m.id
    ORDER BY m.id
""")

_SET_SERIAL = text("UPDATE monographs SET serial_id = :serial_id WHERE id = :id")


def find_monograph_serial_candidates(conn: Connection) -> list[MonographSerialCandidates]:
    """Renvoie les monographies à enregistrement source, avec les entrées de `serials` de leurs enregistrements sources."""
    return [
        MonographSerialCandidates(
            r.id,
            r.title,
            r.publisher_id,
            r.proceedings,
            r.serial_id,
            tuple(r.with_issn),
            tuple(r.without_issn),
        )
        for r in conn.execute(_SERIAL_CANDIDATES)
    ]


def set_monograph_serial(conn: Connection, monograph_id: int, serial_id: int | None) -> None:
    """Pose le `serial_id` d'une monographie."""
    conn.execute(_SET_SERIAL, {"id": monograph_id, "serial_id": serial_id})


def _series_by_monograph(
    candidates: list[MonographSerialCandidates], repo: SerialStore
) -> dict[int, int]:
    """Renvoie la série sans ISSN de chaque monographie qui en a une, trouvée ou créée dans `serials`."""
    proceedings = {m.monograph_id: m.proceedings for m in candidates}
    series: dict[int, int] = {}
    for group in group_series(
        [
            VolumeTitle(m.monograph_id, m.title, m.publisher_id)
            for m in candidates
            if not m.with_issn
        ]
    ):
        if not normalize_text(group.title):
            continue
        series_id = repo.serial_for_title(group.title, group.publisher_id)
        kind = (
            SerialType.PROCEEDINGS
            if all(proceedings[i] for i in group.volume_ids)
            else SerialType.BOOK_SERIES
        )
        repo.set_serial_type_if_unknown(series_id, kind)
        series |= dict.fromkeys(group.volume_ids, series_id)
    return series


def run_link_monographs_to_collections(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Rattache les monographies à leur entrée de `serials`, et journalise chaque changement et chaque conflit."""
    candidates = find_monograph_serial_candidates(conn)
    series = _series_by_monograph(candidates, SerialStore(conn))
    changes: list[tuple[MonographSerialCandidates, MonographSerialChoice]] = []
    conflicts: list[tuple[MonographSerialCandidates, MonographSerialChoice]] = []
    for m in candidates:
        choice = choose_monograph_serial(m.with_issn, m.without_issn, series.get(m.monograph_id))
        if choice.conflict:
            conflicts.append((m, choice))
        elif choice.serial_id != m.serial_id:
            changes.append((m, choice))
    metrics = PhaseMetrics()
    if not (changes or conflicts):
        return metrics
    for m, choice in changes:
        set_monograph_serial(conn, m.monograph_id, choice.serial_id)
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info(
            "Monographie %d « %s » rattachée à %s (au lieu de %s)",
            m.monograph_id,
            m.title,
            choice.serial_id,
            m.serial_id,
            extra={"detail": True},
        )
    for m, choice in conflicts:
        logger.warning(
            "Monographie %d « %s » : plusieurs rattachements possibles %s — laissée en l'état",
            m.monograph_id,
            m.title,
            list(choice.conflict),
            extra={"detail": True},
        )
    metrics.add(
        seen=len(changes) + len(conflicts),
        monographs_linked=len(changes),
        monograph_collection_conflicts=len(conflicts),
        monograph_series=len(set(series.values())),
    )
    metrics.report = (
        f"{quantity(len(set(series.values())), 'série sans ISSN', 'séries sans ISSN')}, "
        f"{quantity(len(changes), 'monographie rattachée', 'monographies rattachées')}, "
        f"{quantity(len(conflicts), 'conflit', 'conflits')}"
    )
    return metrics
