"""Sous-étape de la phase `publishing` : typage des recueils d'actes.

Une revue est un recueil d'actes dans les cas suivants (`domain/serials/containers.py`) :

- une revue de type `unknown` dont la majorité stricte des enregistrements sources sont des articles de congrès, d'après leur type brut, toutes sources confondues ;
- une revue sans ISSN, de n'importe quel type, dont le titre nomme une édition datée (« NuFACT 2022 », « 2024 IEEE SENSORS ») ;
- une revue sans ISSN, de n'importe quel type, dont le titre annonce des actes, hors société savante, académie et institution.
"""

import logging
from typing import NamedTuple

from sqlalchemy import Connection, exists, select, text

from domain.serials.containers import (
    holds_mostly_conference_papers,
    is_dated_event_without_issn,
    is_proceedings_title_without_issn,
)
from domain.serials.issns import IssnStatus
from domain.serials.serial import SerialType
from infrastructure.db.tables import serial_issns, serials
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.serials.serial_label import serial_label
from pipeline.transformation.publishing.serials.store import TYPE_NOT_MANUAL, SerialStore

LABEL = "Typage des recueils d'actes"
"""Libellé de la sous-étape dans le journal de la phase."""

_BY_RECORDS = "articles de congrès"
_BY_DATED_TITLE = "titre daté"
_BY_PROCEEDINGS_TITLE = "titre d'actes"


class SerialRecordTypes(NamedTuple):
    """Enregistrements sources d'une revue : `(source, type brut)` de chacun."""

    serial_id: int
    records: tuple[tuple[str, str | None], ...]


class SerialTitleIssnRow(NamedTuple):
    """Titre d'une revue, et présence d'un ISSN actif."""

    id: int
    title: str
    has_issn: bool


# Type brut de chaque enregistrement source des revues de type inconnu : celui de la source, avant correction.
_RECORD_TYPES_OF_UNKNOWN_SERIALS = text("""
    SELECT j.id,
           array_agg(s.source::text ORDER BY s.id) AS sources,
           array_agg(s.raw_doc_type ORDER BY s.id) AS raw_types
    FROM serials j
    JOIN source_records s ON s.serial_id = j.id
    WHERE j.serial_type = 'unknown' AND NOT 'serial_type' = ANY(j.manual_fields)
    GROUP BY j.id
    ORDER BY j.id
""")


def find_record_types_of_unknown_serials(conn: Connection) -> list[SerialRecordTypes]:
    """Renvoie les revues de type `unknown` à enregistrement source, avec le type brut de chaque enregistrement source."""
    return [
        SerialRecordTypes(r.id, tuple(zip(r.sources, r.raw_types, strict=True)))
        for r in conn.execute(_RECORD_TYPES_OF_UNKNOWN_SERIALS)
    ]


def find_titles_of_non_proceedings_serials(conn: Connection) -> list[SerialTitleIssnRow]:
    """Renvoie les revues d'un autre type que `proceedings`, avec leur titre et la présence d'un ISSN."""
    rows = conn.execute(
        select(
            serials.c.id,
            serials.c.title,
            exists()
            .where(
                serial_issns.c.serial_id == serials.c.id,
                serial_issns.c.status == IssnStatus.ACTIVE,
            )
            .label("has_issn"),
        )
        .where(serials.c.serial_type != SerialType.PROCEEDINGS, TYPE_NOT_MANUAL)
        .order_by(serials.c.id)
    )
    return [SerialTitleIssnRow(r.id, r.title, r.has_issn) for r in rows]


def run_type_proceedings_serials(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Type en recueil d'actes les revues désignées par l'une des trois règles, et journalise chacune avec sa règle."""
    metrics = PhaseMetrics()
    reasons: dict[int, str] = {
        serial.serial_id: _BY_RECORDS
        for serial in find_record_types_of_unknown_serials(conn)
        if holds_mostly_conference_papers(serial.records)
    }
    for serial in find_titles_of_non_proceedings_serials(conn):
        if serial.id in reasons:
            continue
        if is_dated_event_without_issn(serial.title, has_issn=serial.has_issn):
            reasons[serial.id] = _BY_DATED_TITLE
        elif is_proceedings_title_without_issn(serial.title, has_issn=serial.has_issn):
            reasons[serial.id] = _BY_PROCEEDINGS_TITLE
    if not reasons:
        return metrics
    store = SerialStore(conn)
    summaries = store.describe_serials(list(reasons))
    for serial_id, reason in reasons.items():
        store.set_serial_type(serial_id, SerialType.PROCEEDINGS)
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info(
            "Revue typée recueil d'actes (%s) : %s",
            reason,
            serial_label(summaries[serial_id]),
            extra={"detail": True},
        )
    metrics.add(seen=len(reasons), serials_typed_proceedings=len(reasons))
    metrics.report = quantity(
        len(reasons), "revue typée recueil d'actes", "revues typées recueils d'actes"
    )
    return metrics
