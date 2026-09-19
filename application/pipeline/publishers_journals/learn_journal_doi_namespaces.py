"""Sous-étape de la phase `publishers_journals` — calcule les espaces de noms DOI des revues.

Les couples (DOI, revue) des enregistrements de toutes les sources désignent les espaces de noms (`domain/journals/doi_namespaces.py`). La table `journal_doi_namespaces` est recalculée en entier à chaque passage.
"""

import logging

from application.pipeline.libelles import DERNIERE_BRANCHE, accord, etape
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.journals import JournalDoiNamespaceQueries
from domain.journals.doi_namespaces import designated_by_namespace, learn_namespaces


def run_learn_journal_doi_namespaces(
    logger: logging.Logger, *, journal_repo: JournalDoiNamespaceQueries
) -> PhaseMetrics:
    """Calcule les espaces de noms DOI des revues et les enregistre."""
    etape(logger, "Espaces de noms DOI des revues")
    pairs = journal_repo.find_doi_journal_pairs()
    platforms = {p.journal_id for p in pairs if not designated_by_namespace(p.journal_type)}
    namespaces = learn_namespaces(((p.doi, p.journal_id) for p in pairs), platforms=platforms)
    journal_repo.store_doi_namespaces(list(namespaces.values()))
    journals = len({ns.journal_id for ns in namespaces.values()})
    metrics = PhaseMetrics()
    metrics.add(total=len(pairs), journal_doi_namespaces=len(namespaces))
    logger.info(
        "%sTerminé : %s pour %s",
        DERNIERE_BRANCHE,
        accord(len(namespaces), "espace de noms", "espaces de noms"),
        accord(journals, "revue"),
    )
    return metrics
