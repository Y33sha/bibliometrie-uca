"""Sous-étape de la phase `authorships` — supprime les revues vides.

Une revue vide n'a ni enregistrement, ni publication, ni monographie, ni paiement APC. Ses formes de nom partent avec elle : un enregistrement de ce titre chez cet éditeur crée de nouveau sa revue. Le journal garde le titre, l'éditeur et les ISSN de chaque revue supprimée.
"""

import logging

from sqlalchemy import Connection, text

from infrastructure.sql_fragments import active_issns
from pipeline.runtime.observability.libelles import accord
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.journals.journal_label import journal_label
from pipeline.transformation.publishing.journals.store import JournalSummary

LIBELLE = "Revues vides"
"""Libellé de la sous-étape dans le journal de la phase."""

_EMPTY_JOURNALS = text(f"""
    SELECT j.id, j.title, p.name AS publisher, {active_issns("j.id")} AS issns
    FROM journals j LEFT JOIN publishers p ON p.id = j.publisher_id
    WHERE NOT EXISTS (SELECT 1 FROM source_publications s WHERE s.journal_id = j.id)
      AND NOT EXISTS (SELECT 1 FROM publications p WHERE p.journal_id = j.id)
      AND NOT EXISTS (SELECT 1 FROM apc_payments a WHERE a.journal_id = j.id)
      AND NOT EXISTS (SELECT 1 FROM monographs m WHERE m.journal_id = j.id)
    ORDER BY j.id
""")

# Un ISSN déjà présent sans revue tient lieu de la ligne de même valeur des revues supprimées ; leurs autres ISSN
# restent sans revue (`ON DELETE SET NULL`). Les formes de nom partent avec la revue (`ON DELETE CASCADE`).
_DELETE_ISSNS_KNOWN_WITHOUT_JOURNAL = text("""
    DELETE FROM journal_issns i
    WHERE i.journal_id = ANY(:ids)
      AND EXISTS (SELECT 1 FROM journal_issns o WHERE o.issn = i.issn AND o.journal_id IS NULL)
""")
_DELETE_JOURNALS = text("DELETE FROM journals WHERE id = ANY(:ids)")


def delete_empty_journals(conn: Connection) -> list[JournalSummary]:
    """Supprime les revues sans enregistrement, sans publication, sans monographie et sans paiement APC, et les rend."""
    empty = [
        JournalSummary(r.id, r.title, r.publisher, tuple(r.issns))
        for r in conn.execute(_EMPTY_JOURNALS).all()
    ]
    ids = [j.id for j in empty]
    conn.execute(_DELETE_ISSNS_KNOWN_WITHOUT_JOURNAL, {"ids": ids})
    conn.execute(_DELETE_JOURNALS, {"ids": ids})
    return empty


def run_delete_empty_journals(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Supprime les revues vides et journalise chacune."""
    deleted = delete_empty_journals(conn)
    metrics = PhaseMetrics()
    if not deleted:
        return metrics
    for journal in deleted:
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info("Revue vide supprimée : %s", journal_label(journal), extra={"detail": True})
    metrics.add(seen=len(deleted), journals_deleted=len(deleted))
    metrics.report = accord(len(deleted), "revue supprimée", "revues supprimées")
    return metrics
