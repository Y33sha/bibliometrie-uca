"""Interface publique du pipeline : seul module du pipeline que l'API importe.

Elle exporte l'ordre des phases et les recalculs ciblés. `application/` déclare chaque recalcul comme port, et `interfaces/api/deps.py` le remplit depuis ce module.
"""

from pipeline.phase_order import PHASE_ORDER
from pipeline.publications.authorships_queries import AuthorshipsBuild
from pipeline.publications.metadata_correction_queries import PgMetadataCorrectionQueries
from pipeline.structures.countries_queries import CountryQueries
from pipeline.structures.in_perimeter import InPerimeterRecompute
from pipeline.structures.perimeter import PerimeterQueries

__all__ = [
    "PHASE_ORDER",
    "AuthorshipsBuild",
    "CountryQueries",
    "InPerimeterRecompute",
    "PerimeterQueries",
    "PgMetadataCorrectionQueries",
]
