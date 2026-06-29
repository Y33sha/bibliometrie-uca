"""Phase `metadata_correction` — sous-step **journal_by_doi** (rattachement du journal manquant).

Rattache à son journal une `source_publication` qui porte un DOI mais aucun `journal_id`,
lorsque le `doi_prefix` d'un unique journal préfixe ce DOI. Recherche inverse contre la table
journals (décision pure `resolve_journal_by_doi`), à cible data-dépendante : hors du DSL des
règles unaires, traitement à part comme le sous-step cluster.

**Premier** des sous-steps de la phase (avant l'unaire) : le `journal_id` posé ici est commité,
puis l'unaire re-fetch et joint `journal_type` depuis la colonne vivante — la reclassification
`doc_type` journal-dépendante (`JOURNAL_TYPE_MEDIA_TO_MEDIA`, …) a donc lieu dans le même run.

Idempotent et auto-cicatrisant : on repart du `journal_id` **brut reconstruit** (NULL pour une
orpheline), on n'agit que s'il est manquant, et on re-dérive à chaque run. Si le préfixe ne
matche plus (édition du `doi_prefix`), la colonne est restaurée à NULL et le stash retiré.
Possède la clé `raw_metadata.journal_id` ; préserve les clés des autres sous-steps.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import Connection

from application.ports.pipeline.metadata_correction import (
    JournalByDoiRow,
    JournalCorrectionUpdate,
    MetadataCorrectionQueries,
)
from domain.source_publications.correction import JOURNAL_BY_DOI_PREFIX, resolve_journal_by_doi
from domain.source_publications.raw_metadata import raw_value, stash_entry

_PERSIST_BATCH = 5000


def _compute_update(
    row: JournalByDoiRow, journal_prefixes: list[tuple[str, int]]
) -> JournalCorrectionUpdate | None:
    """État cible d'une SP : si le `journal_id` brut est manquant et qu'un préfixe unique
    matche le DOI, on pose ce journal et on stashe le brut (NULL) sous la provenance ; sinon on
    restaure le brut. Retourne `None` si rien ne change (idempotence / auto-cicatrisation). La
    SP possède la clé `raw_metadata.journal_id` ; les autres clés sont préservées."""
    raw_journal_id = raw_value(row.raw_metadata, "journal_id", row.journal_id)
    raw_metadata = {k: v for k, v in row.raw_metadata.items() if k != "journal_id"}

    new_journal_id = raw_journal_id
    if raw_journal_id is None and row.doi:
        matched = resolve_journal_by_doi(row.doi, journal_prefixes)
        if matched is not None:
            new_journal_id = matched
            raw_metadata["journal_id"] = stash_entry(None, JOURNAL_BY_DOI_PREFIX)

    if new_journal_id == row.journal_id and raw_metadata == row.raw_metadata:
        return None
    return JournalCorrectionUpdate(row.id, new_journal_id, raw_metadata)


def compute_updates(
    rows: list[JournalByDoiRow], journal_prefixes: list[tuple[str, int]]
) -> list[JournalCorrectionUpdate]:
    """Calcule les rattachements à persister. Pur (hors I/O) : la décision vit dans
    `resolve_journal_by_doi`, ici on reconstruit le brut, applique la garde « manquant » et
    forme l'état cible."""
    updates = [u for row in rows if (u := _compute_update(row, journal_prefixes)) is not None]
    return updates


@dataclass
class JournalByDoiStats:
    """Bilan de la passe : SP examinées, et SP nouvellement rattachées (journal_id posé)."""

    examined: int
    attached: int


def run(
    conn: Connection, queries: MetadataCorrectionQueries, logger: logging.Logger
) -> JournalByDoiStats:
    """Passe journal_by_doi : rattache le journal des orphelines à DOI dont le préfixe désigne
    un unique journal, et ré-évalue les rattachements existants (auto-cicatrisation)."""
    journal_prefixes = queries.fetch_journal_doi_prefixes(conn)
    rows = queries.fetch_journal_by_doi_candidates(conn)
    logger.info(
        "metadata_correction (journal_by_doi) : %d journaux à préfixe, %d SP examinées",
        len(journal_prefixes),
        len(rows),
    )

    updates = compute_updates(rows, journal_prefixes)
    attached = sum(1 for u in updates if u.journal_id is not None)
    logger.info("  %d rattachements à appliquer (%d journaux posés)", len(updates), attached)

    for start in range(0, len(updates), _PERSIST_BATCH):
        queries.persist_journal_corrections(conn, updates[start : start + _PERSIST_BATCH])
        conn.commit()
    logger.info("✓ %d source_publications rattachées (journal_by_doi)", len(updates))
    return JournalByDoiStats(len(rows), attached)
