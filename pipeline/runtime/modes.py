"""Modes d'exécution du pipeline : sources moissonnées, années, et opérations coûteuses.

- `daily` : les sources incrémentales (HAL), dépôts modifiés depuis le dernier moissonnage quotidien réussi, sans `fetch_stale` ni `harvest_by_person`.
- `full` : toutes les sources moissonnées, sur la plage d'années du run.
"""

from dataclasses import dataclass
from typing import Literal

from domain.sources.registry import HARVESTED_SOURCES, PROFILES

YearSelection = Literal["since_last", "full"]


@dataclass(frozen=True)
class ModePolicy:
    """Politique d'un mode d'exécution."""

    harvest_sources: frozenset[str]
    """Sources moissonnées par le mode. Une source sur option s'ajoute seulement avec `--include-wos`."""
    year_selection: YearSelection
    vacuum_full: bool
    fetch_stale: bool
    """La phase `fetch_stale` réinterroge un à un les enregistrements sources non revus par le moissonnage."""
    harvest_by_person: bool
    """La phase `harvest_by_person` moissonne les sources par l'identifiant des personnes RH."""
    refresh_hal_structures: bool
    """Le référentiel des structures HAL recharge aussi les structures connues, sinon seulement les absentes."""


MODES: dict[str, ModePolicy] = {
    "daily": ModePolicy(
        harvest_sources=frozenset(s for s in HARVESTED_SOURCES if PROFILES[s].incremental),
        year_selection="since_last",
        vacuum_full=False,
        fetch_stale=False,
        harvest_by_person=False,
        refresh_hal_structures=False,
    ),
    "full": ModePolicy(
        harvest_sources=frozenset(HARVESTED_SOURCES),
        year_selection="full",
        vacuum_full=True,
        fetch_stale=True,
        harvest_by_person=True,
        refresh_hal_structures=True,
    ),
}

MODE_NAMES: tuple[str, ...] = tuple(MODES.keys())
