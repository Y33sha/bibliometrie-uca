"""Tâche `affiliations.detect_concatenated_addresses` : détection des adresses concaténées parmi les adresses non examinées (`addresses.is_concatenated`)."""

import json
import logging

from sqlalchemy import Connection, text

from domain.addresses.concatenation import is_concatenated
from infrastructure.db.scalars import scalar_int
from pipeline.runtime.observability.log_format import (
    BRANCH,
    LAST_BRANCH,
    inflect,
    nothing_to_do,
    quantity,
)
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress

CHUNK_SIZE = 10_000
"""Adresses par tranche : la taille borne la mémoire et le nombre d'allers-retours SQL."""

_COUNT_UNEXAMINED = text("SELECT count(*) FROM addresses WHERE is_concatenated IS NULL")

_FETCH_UNEXAMINED = text("""
    SELECT id, raw_text FROM addresses
    WHERE is_concatenated IS NULL AND id > :after
    ORDER BY id LIMIT :limit
""")

_UPDATE = text("""
    UPDATE addresses a SET is_concatenated = t.is_concatenated
    FROM jsonb_to_recordset(CAST(:payload AS jsonb)) AS t(id integer, is_concatenated boolean)
    WHERE a.id = t.id
""")


def detect_concatenated_addresses(
    conn: Connection, logger: logging.Logger, *, chunk_size: int = CHUNK_SIZE
) -> PhaseMetrics:
    """Pose `is_concatenated` sur les adresses non examinées, tranche par tranche. L'appelant commite."""
    total = scalar_int(conn.execute(_COUNT_UNEXAMINED))
    if not total:
        nothing_to_do(logger)
        return PhaseMetrics()

    examined = concatenated = 0
    after_id = 0
    with track_progress(total, BRANCH.rstrip(), logger) as progress:
        while rows := conn.execute(
            _FETCH_UNEXAMINED, {"after": after_id, "limit": chunk_size}
        ).all():
            after_id = rows[-1].id
            payload = [{"id": r.id, "is_concatenated": is_concatenated(r.raw_text)} for r in rows]
            conn.execute(_UPDATE, {"payload": json.dumps(payload)})
            examined += len(rows)
            concatenated += sum(p["is_concatenated"] for p in payload)
            progress.advance(len(rows))

    logger.info(
        "%s%s %s, dont %s",
        LAST_BRANCH,
        quantity(examined, "adresse"),
        inflect(examined, "examinée"),
        quantity(concatenated, "concaténée"),
    )
    return PhaseMetrics(seen=examined, updated=examined)
