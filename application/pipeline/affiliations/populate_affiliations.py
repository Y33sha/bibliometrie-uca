"""Résolution des affiliations sur les authorships sources.

Pose `in_perimeter` sur les `source_authorships` via les adresses résolues (`address_structures`), puis rafraîchit la matview `source_authorship_structures`.
"""

import logging
import time

from sqlalchemy import Connection

from application.pipeline.libelles import DERNIERE_BRANCHE
from application.pipeline.progression import attente
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
    with attente(f"{DERNIERE_BRANCHE}rattachement en cours", logger) as ligne:
        queries.refresh_source_authorship_structures(conn)
        queries.sync_in_perimeter(conn, perimeter_ids=list(perimeter_ids))
        ligne.conclut(f"{DERNIERE_BRANCHE}Terminé en {time.perf_counter() - t0:.1f}s")
    # Commit laissé au caller (CLI commit, tests d'intégration restent dans leur transaction rollbackée).
