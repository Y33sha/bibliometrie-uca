"""
Résolution des affiliations sur les authorships sources.

Pose in_perimeter sur source_authorships via les adresses résolues
(address_structures) et le périmètre restreint, puis rafraîchit la matview
source_authorship_structures (dérivée des adresses + perimeter_structures, sur
le périmètre d'affiliation).

L'orchestrateur dépend du port `AffiliationsQueries`. Le point d'entrée CLI
est dans `interfaces/cli/pipeline/populate_affiliations.py`.
"""

import logging
import time

from sqlalchemy import Connection

from application.ports.pipeline.affiliations import AffiliationsQueries
from domain.sources.registry import ALL_SOURCES


def _step_address_source(
    conn: Connection,
    queries: AffiliationsQueries,
    logger: logging.Logger,
    source: str,
    perimeter_ids: set[int],
    daily: bool = False,
) -> None:
    """Étape : source avec adresses — (re)poser in_perimeter."""
    label = source.capitalize() if source != "openalex" else "OA"

    if not daily:
        n = queries.reset_source_authorships_for(conn, source)
        logger.info(f"  {label} reset : {n} authorships")

    n = queries.set_in_perimeter_from_addresses(
        conn, source=source, perimeter_ids=list(perimeter_ids), daily=daily
    )
    logger.info(f"  {label} in_perimeter = TRUE : {n} authorships")


def show_stats(conn: Connection, queries: AffiliationsQueries, logger: logging.Logger) -> None:
    """Affiche les compteurs in_perimeter par source."""
    for source_name, source_value in [
        ("HAL", "hal"),
        ("OpenAlex", "openalex"),
        ("WoS", "wos"),
        ("ScanR", "scanr"),
        ("theses.fr", "theses"),
    ]:
        total, uca, with_structs = queries.count_source_authorships_stats(conn, source_value)
        logger.info(
            f"  {source_name:10s} : {total} total, {uca} in_perimeter, {with_structs} avec structure_ids"
        )


def run_populate(
    conn: Connection,
    queries: AffiliationsQueries,
    logger: logging.Logger,
    perimeter_ids: set[int],
    *,
    mode: str = "full",
) -> None:
    """Phase source-agnostique : traite toutes les sources systématiquement.

    `resolve_addresses` (en amont) résout les adresses indépendamment des
    sources, donc cette propagation doit l'être aussi — sinon les
    `source_authorships` d'une source non listée restent bloquées sans
    `in_perimeter` malgré une adresse résolue.
    """
    daily = mode == "daily"

    t0 = time.perf_counter()

    logger.info(f"Périmètre restreint : {len(perimeter_ids)} structures")
    if daily:
        logger.info("Mode daily : traitement des authorships récentes uniquement")

    for source in ALL_SOURCES:
        _step_address_source(conn, queries, logger, source, perimeter_ids, daily=daily)

    # `source_authorship_structures` est une matview globale (périmètre
    # d'affiliation) : un refresh unique après que toutes les sources ont
    # réaligné leurs adresses/in_perimeter, en amont du refresh de
    # `authorship_structures` (phase authorships).
    logger.info("Refresh matview source_authorship_structures...")
    queries.refresh_source_authorship_structures(conn)

    elapsed = time.perf_counter() - t0
    logger.info(f"\nTerminé en {elapsed:.1f}s")
    # Commit laissé au caller (CLI commit, tests d'intégration restent dans
    # leur transaction rollbackée). Pattern cohérent avec
    # create_persons_from_source_authorships.run().
