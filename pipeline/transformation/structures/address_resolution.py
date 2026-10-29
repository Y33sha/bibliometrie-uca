"""Tâche `affiliations.resolve_addresses` : rattachement des adresses aux structures, par leurs formes de nom (`name_recognition`).

`address_structures` garde la forme à l'origine de chaque détection.
"""

import logging
from typing import NamedTuple

from sqlalchemy import Connection, text

from infrastructure.db.scalars import scalar_int
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect
from pipeline.runtime.observability.progress import track_progress
from pipeline.transformation.structures.detections import (
    ADDRESS_STRUCTURES,
    Detection,
    sync_detections,
)
from pipeline.transformation.structures.name_recognition import StructureNameMatcher

# Adresses par tranche : la taille borne la mémoire et le nombre d'allers-retours SQL.
CHUNK_SIZE = 10000


def count_addresses(conn: Connection) -> int:
    return scalar_int(conn.execute(text("SELECT count(*) FROM addresses")))


def fetch_addresses_chunk(conn: Connection, *, after_id: int, limit: int) -> list[tuple[int, str]]:
    """Tranche des adresses qui suivent `after_id`, par identifiant croissant."""
    rows = conn.execute(
        text(
            "SELECT a.id, a.normalized_text FROM addresses a "
            "WHERE a.id > :after ORDER BY a.id LIMIT :limit"
        ),
        {"after": after_id, "limit": limit},
    ).all()
    return [(r.id, r.normalized_text) for r in rows]


class ResolutionStats(NamedTuple):
    """Bilan d'une passe de résolution d'adresses."""

    processed: int  # adresses traitées
    in_perimeter: int  # adresses rattachées à au moins une structure du périmètre
    affiliations: int  # liens détectés entre adresse et structure


def run_resolution(
    conn: Connection, perimeter_ids: set[int], logger: logging.Logger
) -> ResolutionStats:
    """Rattache toutes les adresses aux structures, d'après les formes de nom en base."""
    matcher = StructureNameMatcher.load(conn)
    return process_addresses(conn, matcher, perimeter_ids, logger)


def process_addresses(
    conn: Connection,
    matcher: StructureNameMatcher,
    perimeter: set[int],
    logger: logging.Logger,
    *,
    chunk_size: int = CHUNK_SIZE,
) -> ResolutionStats:
    """Rattache toutes les adresses aux structures, tranche par tranche : reconnaissance en mémoire, synchronisation des liens de la tranche (`sync_detections`), puis commit."""

    processed = 0
    in_perimeter_count = 0
    affil_count = 0
    after_id = 0

    with track_progress(count_addresses(conn), BRANCH.rstrip(), logger) as progress:
        while True:
            rows = fetch_addresses_chunk(conn, after_id=after_id, limit=chunk_size)
            if not rows:
                break
            after_id = rows[-1][0]  # tranche triée par id

            addr_ids: list[int] = []
            detections: list[Detection] = []
            for addr_id, normalized_text in rows:
                addr_ids.append(addr_id)
                matches = matcher.resolve(normalized_text)
                if any(m.structure_id in perimeter for m in matches):
                    in_perimeter_count += 1
                for match in matches:
                    detections.append(Detection(addr_id, match.structure_id, match.form_id))
                    affil_count += 1

            sync_detections(conn, ADDRESS_STRUCTURES, detections, scope=addr_ids)
            conn.commit()

            processed += len(rows)
            progress.advance(len(rows))

    if processed > 0:
        logger.info(
            "%sstructures du périmètre identifiées dans %s %s (%.1f%%)",
            LAST_BRANCH,
            in_perimeter_count,
            inflect(in_perimeter_count, "adresse"),
            100 * in_perimeter_count / processed,
        )

    return ResolutionStats(processed, in_perimeter_count, affil_count)
