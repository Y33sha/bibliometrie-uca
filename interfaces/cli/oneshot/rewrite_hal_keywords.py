# STATUS: oneshot (2026-11-01)
"""Écrit les mots-clés des enregistrements sources HAL déjà normalisés, lus dans le TEI.

Le payload de chaque enregistrement source HAL est relu au raw store. Un enregistrement source sans payload au raw store garde ses mots-clés. Un enregistrement source dont les mots-clés changent est mis en file pour la réconciliation, qui recalcule les mots-clés de sa publication.

Usage :
    uv run python -m interfaces.cli.oneshot.rewrite_hal_keywords [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store import UnreadablePayloadError, get_raw_store
from pipeline.ingestion.hal.normalize import parse_tei_keywords
from pipeline.ingestion.hal.payload import hal_text_field

log = setup_logger("rewrite_hal_keywords", os.path.dirname(__file__))

_BATCH = 1000

_COUNT = text("SELECT count(*) FROM source_records WHERE source = 'hal'")

_BATCH_ROWS = text("""
    SELECT id, source_id, keywords
    FROM source_records
    WHERE source = 'hal' AND id > :after
    ORDER BY id
    LIMIT :limit
""")

_WRITE = text("""
    UPDATE source_records sr
    SET keywords = t.keywords
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(id integer, keywords text[])
    WHERE sr.id = t.id
""")


def _rewrite(conn: Connection, *, dry_run: bool) -> None:
    total = conn.execute(_COUNT).scalar_one()
    log.info("%d enregistrements sources HAL à traiter", total)
    store = get_raw_store()
    counts: Counter[str] = Counter()
    after = 0
    while rows := conn.execute(_BATCH_ROWS, {"after": after, "limit": _BATCH}).all():
        changed: list[dict[str, object]] = []
        for r in rows:
            try:
                raw_data = json.loads(store.get("hal", r.source_id))
            except KeyError, UnreadablePayloadError, ValueError:
                counts["sans payload"] += 1
                continue
            keywords = parse_tei_keywords(hal_text_field(raw_data.get("label_xml"))) or None
            if keywords == (r.keywords or None):
                counts["inchangés"] += 1
                continue
            counts["changés"] += 1
            changed.append({"id": r.id, "keywords": keywords})
        if changed and not dry_run:
            conn.execute(_WRITE, {"rows": json.dumps(changed)})
            enqueue(
                conn,
                Queue.SOURCE_RECORD_KEYS,
                "SELECT unnest(CAST(:ids AS integer[]))",
                {"ids": [row["id"] for row in changed]},
            )
            conn.commit()
        after = rows[-1].id
        counts["traités"] += len(rows)
        log.info("%d / %d traités", counts["traités"], total)
    log.info("%s", dict(counts))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Compte les changements sans rien écrire"
    )
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        _rewrite(conn, dry_run=args.dry_run)
        if args.dry_run:
            log.info("Dry-run, rien écrit.")


if __name__ == "__main__":
    main()
