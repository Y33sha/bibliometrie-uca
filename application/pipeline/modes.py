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

from domain.sources.registry import DOI_SEARCHABLE_SOURCES_SET

YearSelection = Literal["since_last", "weekly", "full"]


@dataclass(frozen=True)
class ModePolicy:
    extract_sources: frozenset[str]
    year_selection: YearSelection
    refetch_truncated_oa: bool
    fetch_missing_doi_sources: frozenset[str]
    vacuum_full: bool
    # Gate la phase `oa_status` (Unpaywall, per-publication). Renommé depuis
    # `run_enrich` le 2026-05-26.
    run_oa_status: bool
    # Gate le sub-step `enrich_journals_from_openalex` dans la phase
    # `publishers_journals` (OpenAlex Sources : APC + DOAJ flag + journal_type).
    # `resolve_doi_prefixes` (l'autre sub-step de la phase) tourne dans tous
    # les modes sans gate — il est rapide et alimente le matching publisher.
    run_journal_enrichment: bool
    # True (mode full) = la passe suggest réessaie aussi les suggestions vides
    # (échecs précédents `= []`), au cas où le pool aurait grossi — sans
    # recalculer les positives. False = nouvelles adresses seulement.
    retry_empty_country_suggestions: bool


# WoS : crédit API contractuel limité à 50 000 full records/an. WoS est
# donc réservé au mode `full` (extraction comme cross-imports DOI), et
# exclu des modes daily/weekly où l'appel consommerait du crédit sans
# rapporter d'information non couverte par le mode full.
_FETCH_MISSING_DOI_LIGHT = DOI_SEARCHABLE_SOURCES_SET - {"wos"}


MODES: dict[str, ModePolicy] = {
    "daily": ModePolicy(
        extract_sources=frozenset({"hal"}),
        year_selection="since_last",
        refetch_truncated_oa=True,
        fetch_missing_doi_sources=_FETCH_MISSING_DOI_LIGHT,
        vacuum_full=False,
        # oa_status incrémental (staleness + cap MAX_PER_RUN) : tenable en daily,
        # nécessaire pour que le backlog des jamais-vérifiés s'écoule run après run.
        run_oa_status=True,
        run_journal_enrichment=False,
        retry_empty_country_suggestions=False,
    ),
    "weekly": ModePolicy(
        # Pas de WoS (cf. note crédit API ci-dessus).
        # Pas de theses : renouvellement pas assez fréquent pour justifier l'import hebdomadaire
        extract_sources=frozenset({"hal", "openalex", "scanr"}),
        year_selection="weekly",
        refetch_truncated_oa=True,
        fetch_missing_doi_sources=_FETCH_MISSING_DOI_LIGHT,
        vacuum_full=False,
        run_oa_status=True,
        run_journal_enrichment=False,
        retry_empty_country_suggestions=False,
    ),
    "full": ModePolicy(
        extract_sources=frozenset({"hal", "openalex", "wos", "scanr", "theses"}),
        year_selection="full",
        refetch_truncated_oa=True,
        fetch_missing_doi_sources=DOI_SEARCHABLE_SOURCES_SET,
        vacuum_full=True,
        run_oa_status=True,
        run_journal_enrichment=True,
        retry_empty_country_suggestions=True,
    ),
}

MODE_NAMES: tuple[str, ...] = tuple(MODES.keys())
