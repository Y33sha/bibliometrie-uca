"""Suppression des monographies vides, dans la phase `finalize`.

Une monographie vide est sans enregistrement source et sans publication. Elle se vide quand ses enregistrements rejoignent une autre monographie, par exemple quand l'ISBN arrive sur une monographie créée par son titre. Une monographie encore portée par une publication attend que la phase `publications` recalcule celle-ci. Le journal garde le titre de chaque monographie supprimée.
"""

import logging

from sqlalchemy import Connection, text

from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics

LABEL = "Monographies vides"
"""Libellé de la sous-étape dans le journal de la phase."""

_DELETE_EMPTY = text("""
    DELETE FROM monographs m
    WHERE NOT EXISTS (SELECT 1 FROM source_records s WHERE s.monograph_id = m.id)
      AND NOT EXISTS (SELECT 1 FROM publications p WHERE p.monograph_id = m.id)
    RETURNING m.id, m.title
""")


def delete_empty_monographs(conn: Connection) -> list[tuple[int, str]]:
    """Supprime les monographies sans enregistrement ni publication, et rend `(id, titre)` de chacune."""
    return sorted((r.id, r.title) for r in conn.execute(_DELETE_EMPTY))


def run_delete_empty_monographs(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Supprime les monographies vides et journalise chacune."""
    deleted = delete_empty_monographs(conn)
    metrics = PhaseMetrics()
    if not deleted:
        return metrics
    for monograph_id, title in deleted:
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info(
            "Monographie vide supprimée : %d « %s »", monograph_id, title, extra={"detail": True}
        )
    metrics.add(seen=len(deleted), monographs_deleted=len(deleted))
    metrics.report = quantity(len(deleted), "monographie supprimée", "monographies supprimées")
    return metrics
