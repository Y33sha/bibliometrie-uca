"""Résolution des affiliations sur les authorships sources.

Pose `in_perimeter` sur les `source_authorships` via les adresses résolues (`address_structures`) et le périmètre restreint, puis rafraîchit la matview `source_authorship_structures` (dérivée des adresses et de `perimeter_structures`, sur le périmètre d'affiliation).

Les fonctions dépendent du port `AffiliationsQueries` ; elles sont enchaînées par l'orchestrateur de la phase (`phase.py`).
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
    """Aligne `in_perimeter` de toutes les sources, dérivé de la matview.

    1. Refresh de `source_authorship_structures` (le JOIN adresses ⋈ structures sur le périmètre d'affiliation), en amont du refresh de `authorship_structures` (phase authorships).
    2. Sync source-agnostique de `in_perimeter` depuis cette matview, filtrée au périmètre restreint. Idempotent : un run qui ne change rien n'écrit rien.

    Source-agnostique par construction : `resolve_addresses` résout les adresses indépendamment des sources, donc la propagation l'est aussi (sinon des `source_authorships` resteraient bloquées sans `in_perimeter` malgré une adresse résolue).
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
