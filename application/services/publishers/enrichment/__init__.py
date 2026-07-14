"""Enrichissement (cosmétique) du `country` des éditeurs depuis OpenAlex Publishers.

Purement affichage, **hors pipeline** : lancé à la demande via `interfaces/cli/maintenance/enrich_publishers.py`.
"""

from application.services.publishers.enrichment.from_openalex import (
    run_enrich_publishers_from_openalex,
)

__all__ = [
    "run_enrich_publishers_from_openalex",
]
