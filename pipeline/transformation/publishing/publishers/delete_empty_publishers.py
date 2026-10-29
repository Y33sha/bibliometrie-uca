"""Sous-étape de la phase `finalize` — supprime les éditeurs vides.

Un éditeur vide n'a ni revue, ni monographie, ni enregistrement source, ni publication, ni préfixe DOI, ni paiement APC, ni forme de nom de revue. Une forme de nom de revue rattachée à un éditeur retrouve une revue par son titre chez cet éditeur : l'éditeur de la forme reste. Ses propres formes de nom partent avec lui. Le journal garde le nom de chaque éditeur supprimé.
"""

import logging

from sqlalchemy import Connection, text

from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics

LABEL = "Éditeurs vides"
"""Libellé de la sous-étape dans le journal de la phase."""

# Leurs propres formes de nom partent avec eux (`ON DELETE CASCADE`).
_DELETE_EMPTY_PUBLISHERS = text("""
    DELETE FROM publishers p
    WHERE NOT EXISTS (SELECT 1 FROM serials j WHERE j.publisher_id = p.id)
      AND NOT EXISTS (SELECT 1 FROM doi_prefixes d WHERE d.publisher_id = p.id)
      AND NOT EXISTS (SELECT 1 FROM apc_payments a WHERE a.publisher_id = p.id)
      AND NOT EXISTS (SELECT 1 FROM serial_name_forms f WHERE f.publisher_id = p.id)
      AND NOT EXISTS (SELECT 1 FROM monographs m WHERE m.publisher_id = p.id)
      AND NOT EXISTS (SELECT 1 FROM source_records sr WHERE sr.publisher_id = p.id)
      AND NOT EXISTS (SELECT 1 FROM publications pu WHERE pu.publisher_id = p.id)
    RETURNING p.id, p.name
""")


def delete_empty_publishers(conn: Connection) -> list[tuple[int, str]]:
    """Supprime les éditeurs vides et renvoie `(id, nom)` de chacun."""
    rows = conn.execute(_DELETE_EMPTY_PUBLISHERS).all()
    return sorted((r.id, r.name) for r in rows)


def run_delete_empty_publishers(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Supprime les éditeurs vides et journalise chacun."""
    deleted = delete_empty_publishers(conn)
    metrics = PhaseMetrics()
    if not deleted:
        return metrics
    for publisher_id, name in deleted:
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info("Éditeur vide supprimé : %d « %s »", publisher_id, name, extra={"detail": True})
    metrics.add(seen=len(deleted), publishers_deleted=len(deleted))
    metrics.report = quantity(len(deleted), "éditeur supprimé", "éditeurs supprimés")
    return metrics
