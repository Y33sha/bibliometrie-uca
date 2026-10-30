"""Sous-étape de la phase `publishing` : calcul des espaces de noms DOI des revues.

Les couples (DOI, revue) des enregistrements sources de toutes les sources désignent les espaces de noms (`domain/serials/doi_namespaces.py`). La table `serial_doi_namespaces` est recalculée en entier à chaque passage.
"""

import logging
from collections.abc import Sequence
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.serials.doi_namespaces import DoiNamespace, designated_by_namespace, learn_namespaces
from domain.serials.serial import SerialType
from infrastructure.db.source_record_identifiers import serial_doi_sql
from infrastructure.db.tables import serial_doi_namespaces
from infrastructure.sql_fragments import corrected
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics

LABEL = "Espaces de noms DOI"
"""Libellé de la sous-étape dans le journal de la phase."""


class DoiSerialRow(NamedTuple):
    """Un DOI et la revue attribuée par sa source, avec le type de cette revue."""

    doi: str
    serial_id: int
    serial_type: SerialType


# Une revue attribuée par son espace de noms est notée dans `corrections.serial_id`.
_DOI_SERIAL_PAIRS = text(f"""
    SELECT d.id_value AS doi, s.serial_id, j.serial_type
    FROM source_records s
    JOIN serials j ON j.id = s.serial_id
    JOIN source_record_identifiers d ON d.source_record_id = s.id AND {serial_doi_sql("d", "s")}
    WHERE NOT {corrected("serial_id", "s")}
""")


def find_doi_serial_pairs(conn: Connection) -> list[DoiSerialRow]:
    """Renvoie les couples (DOI, revue) des enregistrements sources, un par DOI donné avec sa revue (`serial_doi_sql`). Une revue attribuée par son espace de noms est exclue du calcul de cet espace."""
    return [
        DoiSerialRow(r.doi, r.serial_id, SerialType(r.serial_type))
        for r in conn.execute(_DOI_SERIAL_PAIRS)
    ]


def store_doi_namespaces(conn: Connection, namespaces: Sequence[DoiNamespace]) -> None:
    """Vide `serial_doi_namespaces`, puis y écrit `namespaces`."""
    conn.execute(serial_doi_namespaces.delete())
    if namespaces:
        conn.execute(serial_doi_namespaces.insert(), [ns._asdict() for ns in namespaces])


def run_learn_serial_doi_namespaces(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Calcule les espaces de noms DOI des revues et les enregistre."""
    pairs = find_doi_serial_pairs(conn)
    platforms = {p.serial_id for p in pairs if not designated_by_namespace(p.serial_type)}
    namespaces = learn_namespaces(((p.doi, p.serial_id) for p in pairs), platforms=platforms)
    store_doi_namespaces(conn, list(namespaces.values()))
    serials = len({ns.serial_id for ns in namespaces.values()})
    metrics = PhaseMetrics()
    metrics.add(seen=len(pairs), serial_doi_namespaces=len(namespaces))
    metrics.report = (
        f"{quantity(len(namespaces), 'espace de noms', 'espaces de noms')} "
        f"pour {quantity(serials, 'revue')}"
    )
    return metrics
