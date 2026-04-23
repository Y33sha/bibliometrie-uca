"""Policies d'exécution du pipeline bibliométrique.

Source unique de vérité pour les modes du pipeline : quelles sources
interroger, quelle plage d'années, quel scope de cross-import, quels
enrichissements. `run_pipeline.py` (adapter CLI) se contente de lire
`MODES[mode]` au lieu de brancher sur la chaîne du mode.

Ajouter ou supprimer un mode = modifier ce fichier (et les `choices`
des CLI qui acceptent `--mode`).
"""

from dataclasses import dataclass
from typing import Literal

from domain.sources import BIBLIO_SOURCES_SET

YearSelection = Literal["since_last", "weekly", "full"]
CrossImportScope = Literal["unprocessed", "all"]


@dataclass(frozen=True)
class ModePolicy:
    extract_sources: frozenset[str]
    year_selection: YearSelection
    refetch_truncated_oa: bool
    cross_import_sources: frozenset[str]
    cross_import_scope: CrossImportScope
    harvest_hal_identifiers: bool
    vacuum_full: bool
    run_enrich: bool


# WoS est exclu des cross-imports en daily/weekly (crédit API limité,
# l'appel n'apporte rien sans nouvelle extraction).
_CROSS_IMPORT_LIGHT = BIBLIO_SOURCES_SET - {"wos"}


MODES: dict[str, ModePolicy] = {
    "daily": ModePolicy(
        extract_sources=frozenset({"hal"}),
        year_selection="since_last",
        refetch_truncated_oa=False,
        cross_import_sources=_CROSS_IMPORT_LIGHT,
        cross_import_scope="unprocessed",
        harvest_hal_identifiers=False,
        vacuum_full=False,
        run_enrich=False,
    ),
    "weekly": ModePolicy(
        extract_sources=frozenset({"hal", "openalex", "scanr"}),
        year_selection="weekly",
        refetch_truncated_oa=True,
        cross_import_sources=_CROSS_IMPORT_LIGHT,
        cross_import_scope="unprocessed",
        harvest_hal_identifiers=False,
        vacuum_full=False,
        run_enrich=False,
    ),
    "full": ModePolicy(
        extract_sources=frozenset({"hal", "openalex", "wos", "scanr", "theses"}),
        year_selection="full",
        refetch_truncated_oa=True,
        cross_import_sources=BIBLIO_SOURCES_SET,
        cross_import_scope="all",
        harvest_hal_identifiers=True,
        vacuum_full=True,
        run_enrich=True,
    ),
}

MODE_NAMES: tuple[str, ...] = tuple(MODES.keys())
