"""Résolution des affiliations sur les authorships sources.

Pose `in_perimeter` sur les `source_authorships` via les adresses résolues (`address_structures`), puis rafraîchit la matview `source_authorship_structures`.
"""

import logging
import time

from sqlalchemy import Connection

from application.ports.pipeline.affiliations import AffiliationsQueries


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
    logger.info(f"Périmètre restreint : {len(perimeter_ids)} structures")

    logger.info("Refresh matview source_authorship_structures...")
    queries.refresh_source_authorship_structures(conn)

    added, removed = queries.sync_in_perimeter(conn, perimeter_ids=list(perimeter_ids))
    logger.info(f"in_perimeter : +{added} / -{removed}")

    elapsed = time.perf_counter() - t0
    logger.info(f"\nTerminé en {elapsed:.1f}s")
    # Commit laissé au caller (CLI commit, tests d'intégration restent dans leur transaction rollbackée).
