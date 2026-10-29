"""Sous-étape de la phase `finalize` — supprime les revues vides.

Une revue vide n'a ni enregistrement, ni publication, ni monographie, ni paiement APC. Ses formes de nom partent avec elle : un enregistrement de ce titre chez cet éditeur crée de nouveau sa revue. Le journal garde le titre, l'éditeur et les ISSN de chaque revue supprimée.
"""

import logging

from sqlalchemy import Connection, text

from infrastructure.sql_fragments import active_issns
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.serials.serial_label import serial_label
from pipeline.transformation.publishing.serials.store import SerialSummary

LABEL = "Publications en série vides"
"""Libellé de la sous-étape dans le journal de la phase."""

_EMPTY_SERIALS = text(f"""
    SELECT j.id, j.title, p.name AS publisher, {active_issns("j.id")} AS issns
    FROM serials j LEFT JOIN publishers p ON p.id = j.publisher_id
    WHERE NOT EXISTS (SELECT 1 FROM source_records s WHERE s.serial_id = j.id)
      AND NOT EXISTS (SELECT 1 FROM publications p WHERE p.serial_id = j.id)
      AND NOT EXISTS (SELECT 1 FROM apc_payments a WHERE a.serial_id = j.id)
      AND NOT EXISTS (SELECT 1 FROM monographs m WHERE m.serial_id = j.id)
    ORDER BY j.id
""")

# Un ISSN déjà présent sans revue prévaut sur la ligne de même valeur d'une revue supprimée ; les autres ISSN restent sans revue (`ON DELETE SET NULL`).
# Les formes de nom partent avec la revue (`ON DELETE CASCADE`).
_DELETE_ISSNS_KNOWN_WITHOUT_SERIAL = text("""
    DELETE FROM serial_issns i
    WHERE i.serial_id = ANY(:ids)
      AND EXISTS (SELECT 1 FROM serial_issns o WHERE o.issn = i.issn AND o.serial_id IS NULL)
""")
_DELETE_SERIALS = text("DELETE FROM serials WHERE id = ANY(:ids)")


def delete_empty_serials(conn: Connection) -> list[SerialSummary]:
    """Supprime les revues sans enregistrement, sans publication, sans monographie et sans paiement APC, et les rend."""
    empty = [
        SerialSummary(r.id, r.title, r.publisher, tuple(r.issns))
        for r in conn.execute(_EMPTY_SERIALS).all()
    ]
    ids = [j.id for j in empty]
    conn.execute(_DELETE_ISSNS_KNOWN_WITHOUT_SERIAL, {"ids": ids})
    conn.execute(_DELETE_SERIALS, {"ids": ids})
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
