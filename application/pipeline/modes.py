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

from domain.sources import DOI_SEARCHABLE_SOURCES_SET

YearSelection = Literal["since_last", "weekly", "full"]
FetchMissingDoiScope = Literal["unprocessed", "all"]


@dataclass(frozen=True)
class ModePolicy:
    extract_sources: frozenset[str]
    year_selection: YearSelection
    refetch_truncated_oa: bool  # TODO: vraiment utile?
    fetch_missing_doi_sources: frozenset[str]
    fetch_missing_doi_scope: FetchMissingDoiScope
    vacuum_full: bool
    # Gate la phase `oa_status` (Unpaywall, per-publication). Renommé depuis
    # `run_enrich` le 2026-05-26.
    run_oa_status: bool
    # Gate le sub-step `enrich_journals_from_openalex` dans la phase
    # `publishers_journals` (OpenAlex Sources : APC + DOAJ flag + journal_type).
    # `resolve_doi_prefixes` (l'autre sub-step de la phase) tourne dans tous
    # les modes sans gate — il est rapide et alimente le matching publisher.
    run_journal_enrichment: bool
    # True = purge complète des authorships canoniques avant rebuild
    # (TRUNCATE + UPDATE FK), pour garantir la convergence absolue.
    # En mode incrémental, le build idempotent suffit.
    rebuild_authorships_full: bool
    # True = remet `addresses.suggested_countries` à NULL pour les adresses
    # déjà tentées sans succès (`= []`) avant la phase countries. Permet de
    # bénéficier d'éventuelles évolutions des heuristiques de matching ou
    # d'un nouveau corpus d'adresses similaires.
    reset_country_suggestions: bool


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
        fetch_missing_doi_scope="unprocessed",
        vacuum_full=False,
        run_oa_status=False,
        run_journal_enrichment=False,
        rebuild_authorships_full=False,
        reset_country_suggestions=False,
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
        run_oa_status=False,
        run_journal_enrichment=False,
        rebuild_authorships_full=False,
        reset_country_suggestions=False,
    ),
    "full": ModePolicy(
        extract_sources=frozenset({"hal", "openalex", "wos", "scanr", "theses"}),
        year_selection="full",
        refetch_truncated_oa=True,
        fetch_missing_doi_sources=DOI_SEARCHABLE_SOURCES_SET,
        fetch_missing_doi_scope="all",
        vacuum_full=True,
        run_oa_status=True,
        run_journal_enrichment=True,
        rebuild_authorships_full=True,
        reset_country_suggestions=True,
    ),
}

MODE_NAMES: tuple[str, ...] = tuple(MODES.keys())
