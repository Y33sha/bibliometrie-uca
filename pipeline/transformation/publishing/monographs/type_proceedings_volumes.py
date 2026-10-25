"""Sous-étape de la phase `publishing` — recalcule la nature des monographies, volume d'actes ou livre.

La nature se recalcule à chaque run d'après les enregistrements, la collection et le titre de la monographie (`is_proceedings_volume`) : elle suit les enregistrements quand ils changent, dans un sens comme dans l'autre. La sous-étape suit le typage des collections, dont elle lit le type.
"""

import logging
from typing import NamedTuple

from sqlalchemy import Connection, bindparam, text

from domain.monographs.proceedings import MonographRecord, is_proceedings_volume
from infrastructure.sql_fragments import declares_conference_sql
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics

LABEL = "Nature des monographies"
"""Libellé de la sous-étape dans le journal de la phase."""


class MonographProceedingsFacts(NamedTuple):
    """Une monographie, sa nature en base, le type de sa collection et ses enregistrements."""

    monograph_id: int
    title: str
    proceedings: bool
    collection_type: str | None
    records: tuple[MonographRecord, ...]


_PROCEEDINGS_FACTS = text(f"""
    SELECT m.id, m.title, m.proceedings, j.serial_type::text AS collection_type,
           coalesce(
               array_agg(sr.source::text ORDER BY sr.id) FILTER (WHERE sr.id IS NOT NULL), '{{}}'
           ) AS sources,
           coalesce(
               array_agg(sr.raw_doc_type ORDER BY sr.id)
                   FILTER (WHERE sr.id IS NOT NULL),
               '{{}}'
           ) AS raw_doc_types,
           coalesce(
               array_agg({declares_conference_sql()} ORDER BY sr.id)
                   FILTER (WHERE sr.id IS NOT NULL),
               '{{}}'
           ) AS declares
    FROM monographs m
    LEFT JOIN serials j ON j.id = m.serial_id
    LEFT JOIN source_records sr ON sr.monograph_id = m.id
    GROUP BY m.id, j.serial_type
    ORDER BY m.id
""")

_SET_PROCEEDINGS = text(
    "UPDATE monographs SET proceedings = :proceedings WHERE id = ANY(:ids)"
).bindparams(bindparam("ids"))


def find_monograph_proceedings_facts(conn: Connection) -> list[MonographProceedingsFacts]:
    """Chaque monographie, avec le type de sa collection et ses enregistrements."""
    return [
        MonographProceedingsFacts(
            r.id,
            r.title,
            r.proceedings,
            r.collection_type,
            tuple(
                MonographRecord(*fields)
                for fields in zip(r.sources, r.raw_doc_types, r.declares, strict=True)
            ),
        )
        for r in conn.execute(_PROCEEDINGS_FACTS)
    ]


def set_monographs_proceedings(
    conn: Connection, monograph_ids: list[int], proceedings: bool
) -> None:
    """Pose la nature d'un ensemble de monographies."""
    if monograph_ids:
        conn.execute(_SET_PROCEEDINGS, {"ids": monograph_ids, "proceedings": proceedings})


def run_type_proceedings_volumes(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Pose la nature recalculée des monographies qui en changent, et journalise chacune."""
    to_proceedings: list[int] = []
    to_books: list[int] = []
    titles: dict[int, str] = {}
    for m in find_monograph_proceedings_facts(conn):
        proceedings = is_proceedings_volume(
            m.records, collection_type=m.collection_type, title=m.title
        )
        if proceedings != m.proceedings:
            (to_proceedings if proceedings else to_books).append(m.monograph_id)
            titles[m.monograph_id] = m.title
    metrics = PhaseMetrics()
    changed = len(to_proceedings) + len(to_books)
    if not changed:
        return metrics
    set_monographs_proceedings(conn, to_proceedings, True)
    set_monographs_proceedings(conn, to_books, False)
    for label, ids in (("volume d'actes", to_proceedings), ("livre", to_books)):
        for monograph_id in ids:
            # Ligne de détail : le terminal la masque, le journal la garde.
            logger.info(
                "Monographie devenue %s : %d « %s »",
                label,
                monograph_id,
                titles[monograph_id],
                extra={"detail": True},
            )
    metrics.add(
        seen=changed,
        monographs_to_proceedings=len(to_proceedings),
        monographs_to_books=len(to_books),
    )
    volumes = quantity(len(to_proceedings), "volume d'actes reconnu", "volumes d'actes reconnus")
    metrics.report = f"{volumes}, {quantity(len(to_books), 'livre reconnu', 'livres reconnus')}"
    return metrics
