"""Phase `metadata_correction` — sous-étape **journal_by_doi** : rattachement de la revue manquante.

Un article ou un article de congrès qui porte un DOI mais aucun `journal_id` reçoit la revue ou la série que désigne l'espace de noms de son DOI, d'après la table `journal_doi_namespaces` (`domain/journals/doi_namespaces.py`). Un livre ou un chapitre n'en reçoit pas : un éditeur publie sous un même espace de noms une revue et des livres (EAC, `10.17184/eac.`), ou une revue et les livres de sa collection (Hermès chez CAIRN, `10.3917/herm.`).

Chaque passage repart du `journal_id` brut reconstruit et agit seulement s'il est nul. Quand l'espace de noms désigne une autre revue, ou plus aucune, la revue suit, et le `journal_id` brut revient avec le retrait de la trace `raw_metadata.journal_id`.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import Connection

from application.pipeline.libelles import DERNIERE_BRANCHE, accord, etape, forme
from application.pipeline.metadata_correction._persist import persist_in_batches
from application.ports.pipeline.metadata_correction import (
    JournalCorrectionRow,
    JournalCorrectionUpdate,
    MetadataCorrectionQueries,
)
from domain.journals.containers import is_book_or_chapter
from domain.journals.doi_namespaces import DoiNamespace, resolve_journal
from domain.source_publications.metadata_correction.journal_by_doi import (
    JOURNAL_BY_DOI_NAMESPACE,
)
from domain.source_publications.raw_metadata import raw_value, stash_entry


def _compute_update(
    row: JournalCorrectionRow, namespaces: Mapping[str, DoiNamespace]
) -> JournalCorrectionUpdate | None:
    """État cible d'une `source_publication`, ou `None` s'il est l'état courant. La clé `raw_metadata.journal_id` appartient à cette sous-étape ; les autres clés sont préservées."""
    raw_journal_id = raw_value(row.raw_metadata, "journal_id", row.journal_id)
    raw_metadata = {k: v for k, v in row.raw_metadata.items() if k != "journal_id"}

    new_journal_id = raw_journal_id
    if raw_journal_id is None and row.doi and not is_book_or_chapter(row.raw_doc_type, row.source):
        namespace = resolve_journal(row.doi, namespaces)
        if namespace is not None:
            new_journal_id = namespace.journal_id
            raw_metadata["journal_id"] = stash_entry(None, JOURNAL_BY_DOI_NAMESPACE)

    if new_journal_id == row.journal_id and raw_metadata == row.raw_metadata:
        return None
    return JournalCorrectionUpdate(row.id, new_journal_id, raw_metadata)


def compute_updates(
    rows: Sequence[JournalCorrectionRow], namespaces: Sequence[DoiNamespace]
) -> list[JournalCorrectionUpdate]:
    """Rattachements à persister."""
    by_namespace = {ns.namespace: ns for ns in namespaces}
    return [u for row in rows if (u := _compute_update(row, by_namespace)) is not None]


@dataclass
class JournalByDoiStats:
    """Bilan de la passe : `source_publications` examinées, et `source_publications` qui reçoivent une revue."""

    examined: int
    attached: int


def run(
    conn: Connection, queries: MetadataCorrectionQueries, logger: logging.Logger
) -> JournalByDoiStats:
    """Rattache leur revue aux `source_publications` sans revue dont le DOI tombe dans un espace de noms, et réévalue les rattachements existants."""
    etape(logger, "Revues non renseignées, identifiables par le DOI du document")
    namespaces = queries.fetch_journal_doi_namespaces(conn)
    rows = queries.fetch_journal_by_doi_candidates(conn)

    updates = compute_updates(rows, namespaces)
    attached = sum(1 for u in updates if u.journal_id is not None)

    persist_in_batches(conn, updates, queries.persist_journal_corrections)
    logger.info(
        "%s%s %s (vers %s)",
        DERNIERE_BRANCHE,
        accord(len(updates), "rattachement"),
        forme(len(updates), "effectué"),
        accord(attached, "revue"),
    )
    return JournalByDoiStats(len(rows), attached)
