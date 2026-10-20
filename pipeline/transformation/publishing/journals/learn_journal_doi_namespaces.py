"""Sous-étape de la phase `publishers_journals` — calcule les espaces de noms DOI des revues.

Les couples (DOI, revue) des enregistrements de toutes les sources désignent les espaces de noms (`domain/journals/doi_namespaces.py`). La table `journal_doi_namespaces` est recalculée en entier à chaque passage.
"""

import logging

from domain.journals.doi_namespaces import designated_by_namespace, learn_namespaces
from pipeline.runtime.observability.libelles import accord
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.journals.journals import JournalGatewayQueries

LIBELLE = "Espaces de noms DOI"
"""Libellé de la sous-étape dans le journal de la phase."""


def run_learn_journal_doi_namespaces(
    logger: logging.Logger, *, journal_repo: JournalGatewayQueries
) -> PhaseMetrics:
    """Calcule les espaces de noms DOI des revues et les enregistre."""
    pairs = journal_repo.find_doi_journal_pairs()
    platforms = {p.journal_id for p in pairs if not designated_by_namespace(p.journal_type)}
    namespaces = learn_namespaces(((p.doi, p.journal_id) for p in pairs), platforms=platforms)
    journal_repo.store_doi_namespaces(list(namespaces.values()))
    journals = len({ns.journal_id for ns in namespaces.values()})
    metrics = PhaseMetrics()
    metrics.add(seen=len(pairs), journal_doi_namespaces=len(namespaces))
    metrics.resume = (
        f"{accord(len(namespaces), 'espace de noms', 'espaces de noms')} "
        f"pour {accord(journals, 'revue')}"
    )
    return metrics
