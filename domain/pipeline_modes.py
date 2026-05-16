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
FetchMissingDoiScope = Literal["unprocessed", "all"]


@dataclass(frozen=True)
class ModePolicy:
    extract_sources: frozenset[str]
    year_selection: YearSelection
    refetch_truncated_oa: bool
    fetch_missing_doi_sources: frozenset[str]
    fetch_missing_doi_scope: FetchMissingDoiScope
    vacuum_full: bool
    run_enrich: bool
    # True = purge complète des authorships canoniques avant rebuild
    # (TRUNCATE + UPDATE FK), pour garantir la convergence absolue.
    # En mode incrémental, le build idempotent suffit.
    rebuild_authorships_full: bool


# WoS : crédit API contractuel limité à 50 000 full records/an. WoS est
# donc réservé au mode `full` (extraction comme cross-imports DOI), et
# exclu des modes daily/weekly où l'appel consommerait du crédit sans
# rapporter d'information non couverte par le mode full.
_FETCH_MISSING_DOI_LIGHT = BIBLIO_SOURCES_SET - {"wos"}


MODES: dict[str, ModePolicy] = {
    "daily": ModePolicy(
        extract_sources=frozenset({"hal"}),
        year_selection="since_last",
        refetch_truncated_oa=False,
        fetch_missing_doi_sources=_FETCH_MISSING_DOI_LIGHT,
        fetch_missing_doi_scope="unprocessed",
        vacuum_full=False,
        run_enrich=False,
        rebuild_authorships_full=False,
    ),
    "weekly": ModePolicy(
        # Pas de WoS (cf. note crédit API ci-dessus).
        # Pas de theses : renouvellement pas assez fréquent pour justifier l'import hebdomadaire
        extract_sources=frozenset({"hal", "openalex", "scanr"}),
        year_selection="weekly",
        refetch_truncated_oa=True,
        fetch_missing_doi_sources=_FETCH_MISSING_DOI_LIGHT,
        fetch_missing_doi_scope="unprocessed",
        vacuum_full=False,
        run_enrich=False,
        rebuild_authorships_full=False,
    ),
    "full": ModePolicy(
        extract_sources=frozenset({"hal", "openalex", "wos", "scanr", "theses"}),
        year_selection="full",
        refetch_truncated_oa=True,
        fetch_missing_doi_sources=BIBLIO_SOURCES_SET,
        fetch_missing_doi_scope="all",
        vacuum_full=True,
        run_enrich=True,
        rebuild_authorships_full=True,
    ),
}

MODE_NAMES: tuple[str, ...] = tuple(MODES.keys())
