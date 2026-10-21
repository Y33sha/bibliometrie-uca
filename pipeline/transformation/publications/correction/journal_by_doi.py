"""Phase `metadata_correction` — sous-étape **journal_by_doi** : rattachement de la revue manquante par l'espace de noms du DOI (`attach_journal_by_doi`), d'après la table `journal_doi_namespaces`."""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.journals.doi_namespaces import DoiNamespace
from domain.source_records.metadata_correction.journal_by_doi import attach_journal_by_doi
from pipeline.runtime.observability.log_format import LAST_BRANCH, inflect, quantity, step
from pipeline.transformation.publications.correction.correction_batches import persist_in_batches
from pipeline.transformation.publications.correction.metadata_correction_queries import (
    JournalCorrectionRow,
    JournalCorrectionUpdate,
    PgMetadataCorrectionQueries,
)


def _compute_update(
    row: JournalCorrectionRow, namespaces: Mapping[str, DoiNamespace]
) -> JournalCorrectionUpdate | None:
    """Mise à jour d'une `source_record`, ou `None` s'il est l'état courant."""
    attached = attach_journal_by_doi(
        row.journal_id, row.doi, row.raw_doc_type, row.source, row.corrections, namespaces
    )
    if tuple(attached) == (row.journal_id, row.corrections):
        return None
    return JournalCorrectionUpdate(row.id, *attached)


def compute_updates(
    rows: Sequence[JournalCorrectionRow], namespaces: Sequence[DoiNamespace]
) -> list[JournalCorrectionUpdate]:
    """Rattachements à persister."""
    by_namespace = {ns.namespace: ns for ns in namespaces}
    return [u for row in rows if (u := _compute_update(row, by_namespace)) is not None]


@dataclass
class JournalByDoiStats:
    """Bilan de la passe : `source_records` examinées, et `source_records` qui reçoivent une revue."""

    examined: int
    attached: int


def run(
    conn: Connection, queries: PgMetadataCorrectionQueries, logger: logging.Logger
) -> JournalByDoiStats:
    """Rattache leur revue aux `source_records` sans revue dont le DOI tombe dans un espace de noms, et réévalue les rattachements existants."""
    step(logger, "Revues non renseignées, identifiables par le DOI du document")
    namespaces = queries.fetch_journal_doi_namespaces(conn)
    rows = queries.fetch_journal_by_doi_candidates(conn)

    updates = compute_updates(rows, namespaces)
    journals = [u.journal_id for u in updates if u.journal_id is not None]
    detached = len(updates) - len(journals)

    persist_in_batches(conn, updates, queries.persist_journal_corrections)
    logger.info(
        "%s%s %s à %s%s",
        LAST_BRANCH,
        quantity(len(journals), "enregistrement source", "enregistrements sources"),
        inflect(len(journals), "rattaché"),
        quantity(len(set(journals)), "revue"),
        f", {quantity(detached, 'rattachement')} {inflect(detached, 'retiré')}" if detached else "",
    )
    return JournalByDoiStats(len(rows), len(journals))
