"""Policies d'exécution du pipeline bibliométrique.

Référentiel unique des modes : quelles sources interroger, quelle stratégie d'années, et les bascules de coût (vacuum, rafraîchissement des documents périmés).

Deux modes :
- `daily` : HAL seul, notices modifiées depuis la dernière extraction quotidienne réussie, sans `fetch_stale` ni `harvest_by_person` ;
- `full` : toutes les sources sauf WoS, plage d'années (depuis une ancre fixe).

WoS est opt-in (`--include-wos`) : crédit API contractuel limité, donc exclue par défaut pour ne pas multiplier les 429.

L'ancre du range `full` est `--start-year` (défaut : config `pipeline_start_year_full`).

Ajouter ou supprimer un mode = modifier ce fichier (et les `choices` des CLI qui acceptent `--mode`).
"""

from dataclasses import dataclass
from typing import Literal

YearSelection = Literal["since_last", "full"]


@dataclass(frozen=True)
class ModePolicy:
    harvest_sources: frozenset[str]
    year_selection: YearSelection
    vacuum_full: bool
    # True (mode full) : `fetch_stale` refetche un par un les documents que l'extraction bulk n'a pas revus. False : la phase est sautée ; les runs full rafraîchissent le stock en bulk.
    fetch_stale: bool
    # True (mode full) : la phase `harvest_by_person` moissonne les sources par l'identifiant des personnes RH. False : la phase est sautée.
    harvest_by_person: bool
    # True (mode full) : le référentiel des structures HAL relit aussi ses structures anciennes. False : seules les structures absentes sont chargées.
    refresh_hal_structures: bool


MODES: dict[str, ModePolicy] = {
    "daily": ModePolicy(
        harvest_sources=frozenset({"hal"}),
        year_selection="since_last",
        vacuum_full=False,
        fetch_stale=False,
        harvest_by_person=False,
        refresh_hal_structures=False,
    ),
    "full": ModePolicy(
        # WoS exclu par défaut (opt-in `--include-wos`) ; theses inclus.
        harvest_sources=frozenset({"hal", "openalex", "scanr", "theses", "datacite"}),
        year_selection="full",
        vacuum_full=True,
        fetch_stale=True,
        harvest_by_person=True,
        refresh_hal_structures=True,
    ),
}

MODE_NAMES: tuple[str, ...] = tuple(MODES.keys())
