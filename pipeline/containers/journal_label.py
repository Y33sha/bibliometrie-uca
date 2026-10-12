"""Libellé d'une revue dans le journal du pipeline."""

from application.ports.pipeline.journals import JournalSummary


def journal_label(journal: JournalSummary) -> str:
    """Identifiant, titre, éditeur et ISSN : `12365 « Livestock Science » (Elsevier BV, 1871-1413/1878-0490)`."""
    issns = "/".join(journal.issns) or "sans ISSN"
    return f"{journal.id} « {journal.title} » ({journal.publisher or 'sans éditeur'}, {issns})"
