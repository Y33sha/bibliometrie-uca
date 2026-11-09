"""Interface publique du pipeline : seul module du pipeline que l'API importe.

Elle exporte l'ordre des phases et les recalculs ciblés. `application/` déclare chaque recalcul comme port, et `interfaces/api/deps.py` le remplit depuis ce module.
"""

from pipeline.transformation.countries.refresh_source_record_countries import CountryRecompute
from pipeline.transformation.publications.publication_perimeter import (
    PublicationPerimeterRecompute,
)
from pipeline.transformation.publications.publication_recompute import PublicationRecompute
from pipeline.transformation.publishing.publication_counts import PublicationCountRecompute
from pipeline.transformation.publishing.serials.serial_merge import SerialRecompute
from pipeline.transformation.structures.perimeter import PerimeterStructures
from pipeline.transformation.structures.perimeter_evidence import (
    SourceContributionPerimeterRecompute,
)

PHASE_ORDER: tuple[str, ...] = (
    "harvest",
    "harvest_by_person",
    "fetch_missing",
    "fetch_stale",
    "fetch_truncated",
    "normalize",
    "affiliations",
    "resolve_ra",
    "publishing",
    "metadata_correction",
    "publications",
    "author_grouping",
    "persons",
    "finalize",
    "relations",
    "subjects",
    "oa_status",
)
"""Noms des phases, dans l'ordre d'exécution de `pipeline.phases.PHASES`."""

__all__ = [
    "PHASE_ORDER",
    "CountryRecompute",
    "SourceContributionPerimeterRecompute",
    "SerialRecompute",
    "PerimeterStructures",
    "PublicationCountRecompute",
    "PublicationPerimeterRecompute",
    "PublicationRecompute",
]
