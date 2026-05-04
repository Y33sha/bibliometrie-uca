"""
Résolution des affiliations sur les authorships sources.

Peuple in_perimeter et structure_ids sur source_authorships en utilisant
les adresses résolues (address_structures) et les périmètres configurés.

Deux périmètres :
  - restreint : UCA + labos tutellés → sert pour in_perimeter
  - large : restreint + partenaires (CHU, INP…) → sert pour structure_ids

L'orchestrateur dépend du port `AffiliationsQueries`. Le point d'entrée CLI
est dans `interfaces/cli/pipeline/populate_affiliations.py`.
"""

import time
from typing import Any

from application.ports.affiliations import AffiliationsQueries
from domain.sources import BIBLIO_SOURCES


def _step_address_source(
    cur: Any,
    queries: AffiliationsQueries,
    logger: Any,
    source: str,
    perimeter_ids: Any,
    wide_ids: Any,
    daily: bool = False,
) -> None:
    """Étape : source avec adresses — calculer in_perimeter + structure_ids."""
    label = source.capitalize() if source != "openalex" else "OA"

    if not daily:
        n = queries.reset_source_authorships_for(cur, source)
        logger.info(f"  {label} reset : {n} authorships")

    n = queries.set_in_perimeter_from_addresses(
        cur, source=source, perimeter_ids=list(perimeter_ids), daily=daily
    )
    logger.info(f"  {label} in_perimeter = TRUE : {n} authorships")

    n = queries.set_structure_ids_from_addresses(
        cur, source=source, wide_ids=list(wide_ids), daily=daily
    )
    logger.info(f"  {label} structure_ids : {n} authorships")


def step3d_theses(
    cur: Any,
    queries: AffiliationsQueries,
    logger: Any,
    wide_ids: Any,
    daily: bool = False,
) -> None:
    """Étape 3d : theses.fr — résoudre structure_ids via adresses.

    in_perimeter est déjà à TRUE (posé par normalize_theses), on ne le reset pas.
    """
    n = queries.set_theses_structure_ids(cur, wide_ids=list(wide_ids), daily=daily)
    logger.info(f"Étape 3d — theses.fr structure_ids : {n} authorships")


def show_stats(cur: Any, queries: AffiliationsQueries, logger: Any) -> None:
    """Affiche les compteurs in_perimeter par source."""
    for source_name, source_value in [
        ("HAL", "hal"),
        ("OpenAlex", "openalex"),
        ("WoS", "wos"),
        ("ScanR", "scanr"),
        ("theses.fr", "theses"),
    ]:
        total, uca, with_structs = queries.count_source_authorships_stats(cur, source_value)
        logger.info(
            f"  {source_name:10s} : {total} total, {uca} in_perimeter, {with_structs} avec structure_ids"
        )


def run_populate(
    cur: Any,
    conn: Any,
    queries: AffiliationsQueries,
    logger: Any,
    perimeter_ids: set[int],
    wide_ids: set[int],
    *,
    mode: str = "full",
) -> None:
    """Phase source-agnostique : traite toutes les sources systématiquement.

    `resolve_addresses` (en amont) résout les adresses indépendamment des
    sources, donc cette propagation doit l'être aussi — sinon les
    `source_authorships` d'une source non listée restent bloquées sans
    `structure_ids` malgré une adresse résolue.
    """
    daily = mode == "daily"

    t0 = time.perf_counter()

    logger.info(f"Périmètre restreint : {len(perimeter_ids)} structures")
    logger.info(f"Périmètre large     : {len(wide_ids)} structures")
    if daily:
        logger.info("Mode daily : traitement des authorships récentes uniquement")

    for source in BIBLIO_SOURCES:
        _step_address_source(cur, queries, logger, source, perimeter_ids, wide_ids, daily=daily)
    step3d_theses(cur, queries, logger, wide_ids, daily=daily)

    conn.commit()
    elapsed = time.perf_counter() - t0
    logger.info(f"\nTerminé en {elapsed:.1f}s")
