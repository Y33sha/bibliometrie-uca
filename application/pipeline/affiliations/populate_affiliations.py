"""Résolution des affiliations sur les authorships sources.

Pose `in_perimeter` sur les `source_authorships` via les adresses résolues (`address_structures`), puis rafraîchit la matview `source_authorship_structures`.
"""

import logging
import time

from sqlalchemy import Connection

from application.ports.pipeline.affiliations.in_perimeter import AffiliationsQueries


def run_populate(
    conn: Connection,
    queries: AffiliationsQueries,
    logger: logging.Logger,
    perimeter_ids: set[int],
) -> None:
    """Renseigne les affiliations des `source_authorships`

    1. Refresh de la matview `source_authorship_structures`.
    2. Sync de `in_perimeter` (BOOL) depuis cette matview.
    """
    t0 = time.perf_counter()
    logger.info("Périmètre restreint : %s structures", len(perimeter_ids))

    logger.info("Refresh matview source_authorship_structures...")
    queries.refresh_source_authorship_structures(conn)

    added, removed = queries.sync_in_perimeter(conn, perimeter_ids=list(perimeter_ids))
    logger.info("in_perimeter : +%s / -%s", added, removed)

    elapsed = time.perf_counter() - t0
    logger.info("\nTerminé en %.1fs", elapsed)
    # Commit laissé au caller (CLI commit, tests d'intégration restent dans leur transaction rollbackée).
