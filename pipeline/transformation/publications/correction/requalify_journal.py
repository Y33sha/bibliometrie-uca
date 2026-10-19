"""Requalification des publications d'une revue, après un changement de son `journal_type`."""

from sqlalchemy import Connection

from pipeline.transformation.publications.correction.correct_unary import (
    compute_updates,
    hal_origin_ids,
)
from pipeline.transformation.publications.correction.metadata_correction_queries import (
    PgMetadataCorrectionQueries,
)
from pipeline.transformation.publications.lifecycle import refresh
from pipeline.transformation.publications.reconciliation.refresh import PublicationStore


def correct_journal_records(conn: Connection, journal_id: int) -> int:
    """Recalcule et persiste les corrections unaires des `source_publications` d'une revue. Retourne le nombre de `source_publications` corrigées."""
    queries = PgMetadataCorrectionQueries()
    rows = queries.fetch_for_unary_correction_by_journal(conn, journal_id)
    hal_rows = {
        row.source_id: row
        for row in queries.fetch_for_unary_correction_by_hal_ids(conn, hal_origin_ids(rows))
    }
    updates = compute_updates(rows, hal_rows, queries.fetch_language_forms(conn))
    return queries.persist_corrections(conn, updates)


def requalify_journal_publications(conn: Connection, journal_id: int) -> int:
    """Rejoue les corrections des `source_publications` de la revue, puis recalcule chacune de ses publications.

    Retourne le nombre de publications dont le `doc_type` change. Une publication supprimée par le recalcul n'est pas comptée.
    """
    store = PublicationStore(conn)
    pub_ids = store.find_ids_by_journal_id(journal_id)
    if not pub_ids:
        return 0
    before = store.find_doc_types_by_ids(pub_ids)
    correct_journal_records(conn, journal_id)
    for pub_id in pub_ids:
        refresh(store, pub_id)
    after = store.find_doc_types_by_ids(pub_ids)
    return sum(1 for pub_id, doc_type in before.items() if after.get(pub_id, doc_type) != doc_type)
