"""Enrichissement (cosmétique) des éditeurs depuis des sources externes.

Pays, ROR et type d'éditeur — purement affichage, donc **hors pipeline** : lancé à
la demande via `interfaces/cli/maintenance/enrich_publishers.py`, qui enchaîne les
trois orchestrateurs dans l'ordre (OpenAlex pose `country`+`ror` ; Crossref Members
rattrape les `country` manquants ; ROR dérive `publisher_type` depuis le `ror`).
"""

from application.services.publishers.enrichment.from_crossref_members import (
    CrossrefMemberFetcher,
    run_enrich_publishers_from_crossref_members,
)
from application.services.publishers.enrichment.from_openalex import (
    run_enrich_publishers_from_openalex,
)
from application.services.publishers.enrichment.from_ror import (
    RorFetcher,
    run_enrich_publishers_from_ror,
)

__all__ = [
    "CrossrefMemberFetcher",
    "RorFetcher",
    "run_enrich_publishers_from_crossref_members",
    "run_enrich_publishers_from_openalex",
    "run_enrich_publishers_from_ror",
]
