"""Sous-étape `serial_by_doi` de la phase `metadata_correction` : rattachement de la revue manquante par l'espace de noms des DOI (`attach_serial_by_doi`), d'après la table `serial_doi_namespaces`."""

import logging
from collections.abc import Mapping, Sequence

from sqlalchemy import Connection

from domain.serials.doi_namespaces import DoiNamespace
from domain.source_records.metadata_correction.serial_by_doi import attach_serial_by_doi
from pipeline.runtime.observability.log_format import LAST_BRANCH, inflect, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publications.correction.correction_batches import persist_in_batches
from pipeline.transformation.publications.correction.correction_store import (
    SerialCorrectionRow,
    SerialCorrectionUpdate,
    SourceRecordCorrectionStore,
)


def _compute_update(
    row: SerialCorrectionRow, namespaces: Mapping[str, DoiNamespace]
) -> SerialCorrectionUpdate | None:
    """Calcule la mise à jour d'un enregistrement source, ou `None` si rien ne change."""
    attached = attach_serial_by_doi(
        row.serial_id, row.dois, row.raw_doc_type, row.source, row.corrections, namespaces
    )
    if tuple(attached) == (row.serial_id, row.corrections):
        return None
    return SerialCorrectionUpdate(row.id, *attached)


def compute_updates(
    rows: Sequence[SerialCorrectionRow], namespaces: Sequence[DoiNamespace]
) -> list[SerialCorrectionUpdate]:
    """Calcule les rattachements à écrire."""
    by_namespace = {ns.namespace: ns for ns in namespaces}
    return [u for row in rows if (u := _compute_update(row, by_namespace)) is not None]


def run(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Rattache à leur revue les enregistrements sources sans revue à DOI relevant d'un espace de noms, et réévalue les rattachements existants. Renvoie les enregistrements sources examinés et mis à jour."""
    store = SourceRecordCorrectionStore(conn)
    namespaces = store.fetch_serial_doi_namespaces()
    rows = store.fetch_serial_by_doi_candidates()

    updates = compute_updates(rows, namespaces)
    serials = [u.serial_id for u in updates if u.serial_id is not None]
    detached = len(updates) - len(serials)

    written = persist_in_batches(conn, updates, store.persist_serial_corrections)
    logger.info(
        "%s%s %s à %s%s",
        LAST_BRANCH,
        quantity(len(serials), "enregistrement source", "enregistrements sources"),
        inflect(len(serials), "rattaché"),
        quantity(len(set(serials)), "revue"),
        f", {quantity(detached, 'rattachement')} {inflect(detached, 'retiré')}" if detached else "",
    )
    return PhaseMetrics(seen=len(rows), updated=written)
