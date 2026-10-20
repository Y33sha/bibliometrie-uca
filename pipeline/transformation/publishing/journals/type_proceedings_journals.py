"""Sous-étape de la phase `publishers_journals` — type en recueil d'actes les revues qui en sont.

Trois règles de `domain/journals/containers.py` désignent un recueil d'actes :

- une revue de type `unknown` dont la majorité stricte des documents sont des articles de congrès, d'après le type brut de chaque document, toutes sources confondues ;
- une revue sans ISSN, de n'importe quel type, dont le titre nomme une édition datée (« NuFACT 2022 », « 2024 IEEE SENSORS ») ;
- une revue sans ISSN, de n'importe quel type, dont le titre annonce des actes, hors société savante, académie et institution.
"""

import logging
from typing import NamedTuple

from sqlalchemy import Connection, exists, select, text

from domain.journals.containers import (
    holds_mostly_conference_papers,
    is_dated_event_without_issn,
    is_proceedings_title_without_issn,
)
from domain.journals.issns import IssnStatus
from domain.journals.journal import JournalType
from infrastructure.db.tables import journal_issns, journals
from infrastructure.sql_fragments import raw_column
from pipeline.runtime.observability.libelles import accord
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.journals.journal_label import journal_label
from pipeline.transformation.publishing.journals.store import TYPE_NOT_MANUAL, JournalStore

LIBELLE = "Typage des recueils d'actes"
"""Libellé de la sous-étape dans le journal de la phase."""

_BY_RECORDS = "articles de congrès"
_BY_DATED_TITLE = "titre daté"
_BY_PROCEEDINGS_TITLE = "titre d'actes"


class JournalRecordTypes(NamedTuple):
    """Les documents d'une revue : `(source, type brut)` de chacun."""

    journal_id: int
    records: tuple[tuple[str, str | None], ...]


class JournalTitleIssnRow(NamedTuple):
    """Titre d'une revue, et présence d'un ISSN actif."""

    id: int
    title: str
    has_issn: bool


# Type brut de chaque document des revues de type inconnu : celui de la source, avant correction.
_RECORD_TYPES_OF_UNKNOWN_JOURNALS = text(f"""
    SELECT j.id,
           array_agg(s.source::text ORDER BY s.id) AS sources,
           array_agg({raw_column("doc_type", "s")} ORDER BY s.id) AS raw_types
    FROM journals j
    JOIN source_publications s ON s.journal_id = j.id
    WHERE j.journal_type = 'unknown' AND NOT 'journal_type' = ANY(j.manual_fields)
    GROUP BY j.id
    ORDER BY j.id
""")


def find_record_types_of_unknown_journals(conn: Connection) -> list[JournalRecordTypes]:
    """Les revues de type `unknown` qui ont au moins un document, avec le type brut de chaque document."""
    return [
        JournalRecordTypes(r.id, tuple(zip(r.sources, r.raw_types, strict=True)))
        for r in conn.execute(_RECORD_TYPES_OF_UNKNOWN_JOURNALS)
    ]


def find_titles_of_non_proceedings_journals(conn: Connection) -> list[JournalTitleIssnRow]:
    """Les revues d'un autre type que `proceedings`, avec leur titre et la présence d'un ISSN."""
    rows = conn.execute(
        select(
            journals.c.id,
            journals.c.title,
            exists()
            .where(
                journal_issns.c.journal_id == journals.c.id,
                journal_issns.c.status == IssnStatus.ACTIVE,
            )
            .label("has_issn"),
        )
        .where(journals.c.journal_type != JournalType.PROCEEDINGS, TYPE_NOT_MANUAL)
        .order_by(journals.c.id)
    )
    return [JournalTitleIssnRow(r.id, r.title, r.has_issn) for r in rows]


def run_type_proceedings_journals(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Type en recueil d'actes les revues que désigne l'une des trois règles, et journalise chacune avec la règle qui la désigne."""
    metrics = PhaseMetrics()
    reasons: dict[int, str] = {
        journal.journal_id: _BY_RECORDS
        for journal in find_record_types_of_unknown_journals(conn)
        if holds_mostly_conference_papers(journal.records)
    }
    for journal in find_titles_of_non_proceedings_journals(conn):
        if journal.id in reasons:
            continue
        if is_dated_event_without_issn(journal.title, has_issn=journal.has_issn):
            reasons[journal.id] = _BY_DATED_TITLE
        elif is_proceedings_title_without_issn(journal.title, has_issn=journal.has_issn):
            reasons[journal.id] = _BY_PROCEEDINGS_TITLE
    if not reasons:
        return metrics
    store = JournalStore(conn)
    summaries = store.describe_journals(list(reasons))
    for journal_id, reason in reasons.items():
        store.set_journal_type(journal_id, JournalType.PROCEEDINGS)
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info(
            "Revue typée recueil d'actes (%s) : %s",
            reason,
            journal_label(summaries[journal_id]),
            extra={"detail": True},
        )
    metrics.add(seen=len(reasons), journals_typed_proceedings=len(reasons))
    metrics.report = accord(
        len(reasons), "revue typée recueil d'actes", "revues typées recueils d'actes"
    )
    return metrics
