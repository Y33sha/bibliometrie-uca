"""Interface publique du pipeline : seul module du pipeline que l'API importe.

Elle exporte l'ordre des phases et les recalculs ciblés. `application/` déclare chaque recalcul comme port, et `interfaces/api/deps.py` le remplit depuis ce module.
"""

from pipeline.graph import PHASE_ORDER
from pipeline.transformation.countries.refresh_publication_countries import CountryRecompute
from pipeline.transformation.publications.publication_perimeter import (
    PublicationPerimeterRecompute,
)
from pipeline.transformation.publishing.publication_counts import PublicationCountRecompute
from pipeline.transformation.publishing.serials.serial_merge import SerialRecompute
from pipeline.transformation.structures.perimeter import PerimeterStructures
from pipeline.transformation.structures.perimeter_evidence import (
    SourceContributionPerimeterRecompute,
)

__all__ = [
    "PHASE_ORDER",
    "CountryRecompute",
    "SourceContributionPerimeterRecompute",
    "SerialRecompute",
    "PerimeterStructures",
    "PublicationCountRecompute",
    "PublicationPerimeterRecompute",
]
