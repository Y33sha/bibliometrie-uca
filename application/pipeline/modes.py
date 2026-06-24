"""Policies d'exécution du pipeline bibliométrique.

Source unique de vérité pour les modes : quelles sources interroger, quelle
stratégie d'années, et les bascules de coût (vacuum, retry des suggestions de
pays vides). `run_pipeline.py` lit `MODES[mode]` au lieu de brancher sur la
chaîne du mode.

Deux modes :
- `daily` : HAL seul, extraction incrémentale par date (depuis le dernier
  rapport) ;
- `full` : toutes les sources sauf WoS, plage d'années `[ancre … courante]`.

WoS est opt-in (`--include-wos`) : source en fin de vie, crédit API contractuel
limité, donc exclue par défaut pour ne pas multiplier les 429. L'ancre du range
`full` est `--start-year` (défaut : config `pipeline_start_year_full`).

Les bascules invariantes (oa_status, refetch des works OpenAlex tronqués,
enrichissement des journaux) tournent dans tous les modes — toutes incrémentales
et auto-bornées —, elles ne figurent donc pas dans la policy.

Ajouter ou supprimer un mode = modifier ce fichier (et les `choices` des CLI
qui acceptent `--mode`).
"""

from dataclasses import dataclass
from typing import Literal

YearSelection = Literal["since_last", "full"]


@dataclass(frozen=True)
class ModePolicy:
    extract_sources: frozenset[str]
    year_selection: YearSelection
    vacuum_full: bool
    # True (mode full) : la passe suggest réessaie aussi les suggestions de pays
    # vides (échecs précédents `= []`), au cas où le pool aurait grossi — sans
    # recalculer les positives. False : nouvelles adresses seulement.
    retry_empty_country_suggestions: bool


MODES: dict[str, ModePolicy] = {
    "daily": ModePolicy(
        extract_sources=frozenset({"hal"}),
        year_selection="since_last",
        vacuum_full=False,
        retry_empty_country_suggestions=False,
    ),
    "full": ModePolicy(
        # WoS exclu par défaut (opt-in `--include-wos`) ; theses inclus.
        extract_sources=frozenset({"hal", "openalex", "scanr", "theses"}),
        year_selection="full",
        vacuum_full=True,
        retry_empty_country_suggestions=True,
    ),
}

MODE_NAMES: tuple[str, ...] = tuple(MODES.keys())
