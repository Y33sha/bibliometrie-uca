"""Interface publique du pipeline : seul module du pipeline que l'API importe.

Elle exporte l'ordre des phases et les recalculs ciblés. `application/` déclare chaque recalcul comme port, et `interfaces/api/deps.py` le remplit depuis ce module.
"""

from pipeline.graph import PHASE_ORDER
from pipeline.transformation.countries.refresh_publication_countries import CountryRecompute
from pipeline.transformation.publications.publication_perimeter import (
    PublicationPerimeterRecompute,
)
from pipeline.transformation.publishing.journals.journal_merge import JournalRecompute
from pipeline.transformation.publishing.pub_counts import PubCountRecompute
from pipeline.transformation.structures.perimeter import PerimeterStructures
from pipeline.transformation.structures.perimeter_evidence import (
    SourceContributionPerimeterRecompute,
)

__all__ = [
    "PHASE_ORDER",
    "CountryRecompute",
    "SourceContributionPerimeterRecompute",
    "JournalRecompute",
    "PerimeterStructures",
    "PubCountRecompute",
    "PublicationPerimeterRecompute",
]
