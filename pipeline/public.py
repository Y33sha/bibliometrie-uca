"""Interface publique du pipeline : seul module du pipeline que l'API importe.

Elle exporte l'ordre des phases et les recalculs ciblés. `application/` déclare chaque recalcul comme port, et `interfaces/api/deps.py` le remplit depuis ce module.
"""

from pipeline.graph import PHASE_ORDER
from pipeline.transformation.publications.authorships.authorships_queries import AuthorshipsBuild
from pipeline.transformation.publications.publication_perimeter import (
    PublicationPerimeterRecompute,
)
from pipeline.transformation.publishing.journals.journal_merge import JournalRecompute
from pipeline.transformation.publishing.pub_counts import PubCountRecompute
from pipeline.transformation.structures.countries.countries_queries import CountryQueries
from pipeline.transformation.structures.in_perimeter import InPerimeterRecompute
from pipeline.transformation.structures.perimeter import PerimeterQueries

__all__ = [
    "PHASE_ORDER",
    "AuthorshipsBuild",
    "CountryQueries",
    "InPerimeterRecompute",
    "JournalRecompute",
    "PerimeterQueries",
    "PubCountRecompute",
    "PublicationPerimeterRecompute",
]
