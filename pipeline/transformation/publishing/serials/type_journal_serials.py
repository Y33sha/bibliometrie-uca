"""Sous-étape de la phase `publishing` : typage en revue des entrées de type inconnu contenant surtout des articles.

Une entrée de type `unknown` est une revue quand la majorité stricte de ses enregistrements sources sont des articles, d'après leur type brut, toutes sources confondues (`domain/serials/containers.py`). Le typage en recueil d'actes passe avant.
"""

import logging

from sqlalchemy import Connection

from domain.serials.containers import holds_mostly_articles
from domain.serials.serial import SerialType
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.serials.serial_label import serial_label
from pipeline.transformation.publishing.serials.store import SerialStore
from pipeline.transformation.publishing.serials.type_proceedings_serials import (
    find_record_types_of_unknown_serials,
)

LABEL = "Typage des revues"
"""Libellé de la sous-étape dans le journal de la phase."""


def run_type_journal_serials(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Type en revue les entrées de type inconnu contenant surtout des articles, et journalise chacune."""
    metrics = PhaseMetrics()
    serial_ids = [
        serial.serial_id
        for serial in find_record_types_of_unknown_serials(conn)
        if holds_mostly_articles(serial.records)
    ]
    if not serial_ids:
        return metrics
    store = SerialStore(conn)
    summaries = store.describe_serials(serial_ids)
    for serial_id in serial_ids:
        store.set_serial_type(serial_id, SerialType.JOURNAL)
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info(
            "Entrée typée revue : %s", serial_label(summaries[serial_id]), extra={"detail": True}
        )
    metrics.add(seen=len(serial_ids), serials_typed_journal=len(serial_ids))
    metrics.report = quantity(len(serial_ids), "entrée typée revue", "entrées typées revues")
    return metrics
