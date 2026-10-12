"""Interface publique du pipeline : seul module du pipeline que l'API importe.

Elle exporte l'ordre des phases et les recalculs ciblés. `application/` déclare chaque recalcul comme port, et `interfaces/api/deps.py` le remplit depuis ce module.
"""

from pipeline.containers.journal_merge import JournalRecompute
from pipeline.containers.pub_counts import PubCountRecompute
from pipeline.publications.authorships_queries import AuthorshipsBuild
from pipeline.publications.publication_perimeter import PublicationPerimeterRecompute
from pipeline.runtime.phase_order import PHASE_ORDER
from pipeline.structures.countries_queries import CountryQueries
from pipeline.structures.in_perimeter import InPerimeterRecompute
from pipeline.structures.perimeter import PerimeterQueries

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
