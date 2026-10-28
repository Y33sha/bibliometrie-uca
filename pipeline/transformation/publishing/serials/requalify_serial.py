"""Requalification des publications d'une revue, après un changement de son `serial_type`."""

from sqlalchemy import Connection

from pipeline.transformation.publications import lifecycle
from pipeline.transformation.publications.correction.correct_unary import (
    compute_updates,
    hal_origin_ids,
)
from pipeline.transformation.publications.correction.correction_store import (
    SourceRecordCorrectionStore,
)
from pipeline.transformation.publications.store import PublicationStore


def correct_serial_records(conn: Connection, serial_id: int) -> int:
    """Recalcule et persiste les corrections unaires des `source_records` d'une revue. Retourne le nombre de `source_records` corrigées."""
    store = SourceRecordCorrectionStore(conn)
    rows = store.fetch_for_unary_correction_by_serial(serial_id)
    hal_rows = {
        row.source_id: row
        for row in store.fetch_for_unary_correction_by_hal_ids(hal_origin_ids(rows))
    }
    updates = compute_updates(rows, hal_rows, store.fetch_missing_hal_ids())
    return store.persist_corrections(updates)


def requalify_serial_publications(conn: Connection, serial_id: int) -> int:
    """Rejoue les corrections des `source_records` de la revue, puis recalcule chacune de ses publications.

    Retourne le nombre de publications dont le `doc_type` change. Une publication supprimée par le recalcul n'est pas comptée.
    """
    store = PublicationStore(conn)
    publication_ids = store.find_ids_by_serial_id(serial_id)
    if not publication_ids:
        return 0
    before = store.find_doc_types_by_ids(publication_ids)
    correct_serial_records(conn, serial_id)
    for publication_id in publication_ids:
        lifecycle.refresh(conn, publication_id)
    after = store.find_doc_types_by_ids(publication_ids)
    return sum(
        1
        for publication_id, doc_type in before.items()
        if after.get(publication_id, doc_type) != doc_type
    )
