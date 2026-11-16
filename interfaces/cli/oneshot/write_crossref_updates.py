# STATUS: oneshot (2026-11-16)
"""Écrit les mises à jour Crossref (`update-to`, `updated-by`) dans `source_extras` des enregistrements sources Crossref déjà normalisés.

Le payload de chaque enregistrement source est relu au raw store. Les publications des enregistrements sources modifiés passent en file de consolidation, qui fusionne leur `source_extras`.

Usage :
    uv run python -m interfaces.cli.oneshot.write_crossref_updates [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter

from sqlalchemy import Connection, text

from domain.types import JsonValue
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store import UnreadablePayloadError, get_raw_store
from pipeline.ingestion.crossref.payload import extract_crossref_updates

log = setup_logger("write_crossref_updates", os.path.dirname(__file__))

_SOURCE_RECORDS = text("SELECT id, source_id FROM source_records WHERE source = 'crossref'")

_WRITE = text("""
    UPDATE source_records sr
    SET source_extras = coalesce(sr.source_extras, '{}'::jsonb) || t.patch,
        updated_at = clock_timestamp()
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(id integer, patch jsonb)
    WHERE sr.id = t.id AND sr.source_extras IS DISTINCT FROM coalesce(sr.source_extras, '{}'::jsonb) || t.patch
    RETURNING sr.id
""")

_PUBLICATIONS = """
    SELECT DISTINCT publication_id FROM source_records
    WHERE id = ANY(:ids) AND publication_id IS NOT NULL
"""


def write_updates(conn: Connection, *, dry_run: bool) -> None:
    """Écrit les mises à jour Crossref des enregistrements sources et marque leurs publications pour la consolidation."""
    store = get_raw_store()
    counts: Counter[str] = Counter()
    without_payload = 0
    rows: list[dict[str, JsonValue]] = []
    for r in conn.execute(_SOURCE_RECORDS):
        try:
            payload = json.loads(store.get("crossref", r.source_id))
        except KeyError, UnreadablePayloadError, ValueError:
            without_payload += 1
            continue
        if patch := extract_crossref_updates(payload):
            rows.append({"id": r.id, "patch": patch})
            counts.update(str(key) for key in patch)
    log.info("Enregistrements sources sans payload : %d", without_payload)
    log.info("Enregistrements sources avec mises à jour : %d (%s)", len(rows), dict(counts))
    if dry_run or not rows:
        return
    written = [row.id for row in conn.execute(_WRITE, {"rows": json.dumps(rows)})]
    marked = enqueue(conn, Queue.PUBLICATIONS, _PUBLICATIONS, {"ids": written})
    log.info(
        "Enregistrements sources modifiés : %d, publications marquées : %d", len(written), marked
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()
    with get_sync_engine().begin() as conn:
        write_updates(conn, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
