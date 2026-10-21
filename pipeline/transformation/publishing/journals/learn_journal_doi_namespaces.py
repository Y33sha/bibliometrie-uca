"""Sous-étape de la phase `publishers_journals` — calcule les espaces de noms DOI des revues.

Les couples (DOI, revue) des enregistrements de toutes les sources désignent les espaces de noms (`domain/journals/doi_namespaces.py`). La table `journal_doi_namespaces` est recalculée en entier à chaque passage.
"""

import logging
from collections.abc import Sequence
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.journals.doi_namespaces import DoiNamespace, designated_by_namespace, learn_namespaces
from domain.journals.journal import JournalType
from infrastructure.db.tables import journal_doi_namespaces
from infrastructure.sql_fragments import corrected
from pipeline.runtime.observability.libelles import accord
from pipeline.runtime.observability.metrics import PhaseMetrics

LIBELLE = "Espaces de noms DOI"
"""Libellé de la sous-étape dans le journal de la phase."""


class DoiJournalRow(NamedTuple):
    """Un DOI et la revue que lui donne sa source, avec le type de cette revue."""

    doi: str
    journal_id: int
    journal_type: JournalType


# Une revue posée par son espace de noms laisse sa trace dans `corrections.journal_id`.
_DOI_JOURNAL_PAIRS = text(f"""
    SELECT s.doi, s.journal_id, j.journal_type
    FROM source_records s
    JOIN journals j ON j.id = s.journal_id
    WHERE s.doi IS NOT NULL AND NOT {corrected("journal_id", "s")}
""")


def find_doi_journal_pairs(conn: Connection) -> list[DoiJournalRow]:
    """Le couple (DOI, revue) de chaque enregistrement. Une revue posée par son espace de noms est exclue : elle ne témoigne pas pour lui."""
    return [
        DoiJournalRow(r.doi, r.journal_id, JournalType(r.journal_type))
        for r in conn.execute(_DOI_JOURNAL_PAIRS)
    ]


def store_doi_namespaces(conn: Connection, namespaces: Sequence[DoiNamespace]) -> None:
    """Vide `journal_doi_namespaces`, puis y écrit `namespaces`."""
    conn.execute(journal_doi_namespaces.delete())
    if namespaces:
        conn.execute(journal_doi_namespaces.insert(), [ns._asdict() for ns in namespaces])


def run_learn_journal_doi_namespaces(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Calcule les espaces de noms DOI des revues et les enregistre."""
    pairs = find_doi_journal_pairs(conn)
    platforms = {p.journal_id for p in pairs if not designated_by_namespace(p.journal_type)}
    namespaces = learn_namespaces(((p.doi, p.journal_id) for p in pairs), platforms=platforms)
    store_doi_namespaces(conn, list(namespaces.values()))
    journals = len({ns.journal_id for ns in namespaces.values()})
    metrics = PhaseMetrics()
    metrics.add(seen=len(pairs), journal_doi_namespaces=len(namespaces))
    metrics.report = (
        f"{accord(len(namespaces), 'espace de noms', 'espaces de noms')} "
        f"pour {accord(journals, 'revue')}"
    )
    return metrics
