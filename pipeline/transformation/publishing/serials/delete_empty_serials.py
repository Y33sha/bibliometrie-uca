"""Sous-étape de la phase `finalize` : suppression des revues vides.

Une revue vide n'a ni ISSN, ni enregistrement source, ni publication, ni monographie, ni paiement APC. Une revue à ISSN reste : supprimée, elle serait recréée au passage suivant pour les séries qui citent ses ISSN. Le journal garde le titre et l'éditeur de chaque revue supprimée.
"""

import logging

from sqlalchemy import Connection, text

from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.serials.serial_label import serial_label
from pipeline.transformation.publishing.serials.store import SerialSummary

LABEL = "Publications en série vides"
"""Libellé de la sous-étape dans le journal de la phase."""

_EMPTY_SERIALS = text("""
    SELECT j.id, j.title, p.name AS publisher
    FROM serials j LEFT JOIN publishers p ON p.id = j.publisher_id
    WHERE NOT EXISTS (SELECT 1 FROM serial_issns i WHERE i.serial_id = j.id)
      AND NOT EXISTS (SELECT 1 FROM source_records s WHERE s.serial_id = j.id)
      AND NOT EXISTS (SELECT 1 FROM publications p WHERE p.serial_id = j.id)
      AND NOT EXISTS (SELECT 1 FROM apc_payments a WHERE a.serial_id = j.id)
      AND NOT EXISTS (SELECT 1 FROM monographs m WHERE m.serial_id = j.id)
    ORDER BY j.id
""")

_DELETE_SERIALS = text("DELETE FROM serials WHERE id = ANY(:ids)")


def delete_empty_serials(conn: Connection) -> list[SerialSummary]:
    """Supprime les revues vides et les renvoie."""
    empty = [
        SerialSummary(r.id, r.title, r.publisher, ()) for r in conn.execute(_EMPTY_SERIALS).all()
    ]
    conn.execute(_DELETE_SERIALS, {"ids": [j.id for j in empty]})
    return empty


def run_delete_empty_serials(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Supprime les revues vides et journalise chacune."""
    deleted = delete_empty_serials(conn)
    metrics = PhaseMetrics()
    if not deleted:
        return metrics
    for serial in deleted:
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info("Revue vide supprimée : %s", serial_label(serial), extra={"detail": True})
    metrics.add(seen=len(deleted), serials_deleted=len(deleted))
    metrics.report = quantity(len(deleted), "revue supprimée", "revues supprimées")
    return metrics
