# STATUS: oneshot (2026-11-01)
"""Écrit la date de publication des enregistrements sources déjà normalisés, avec sa précision.

Le payload de chaque enregistrement source est relu au raw store. Le normaliseur de sa source en tire la date (`publication_date`), et l'année en dérive. Un enregistrement source sans payload au raw store garde sa date à l'année. WoS garde aussi sa date à l'année. Un enregistrement source dont l'année change est mis en file pour la réconciliation.

Usage :
    uv run python -m interfaces.cli.oneshot.rewrite_publication_dates [--sources hal,openalex] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter

from sqlalchemy import Connection, text

from domain.sources.registry import SOURCE_PRIORITY
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store import UnreadablePayloadError, get_raw_store
from pipeline.ingestion.common.normalize import normalizer_builders
from pipeline.ingestion.common.source_records import date_columns
from pipeline.ingestion.common.staging import StagingRow

log = setup_logger("rewrite_publication_dates", os.path.dirname(__file__))

_BATCH = 1000
_EXCLUDED_SOURCES = ("wos",)

_COUNT = text("SELECT count(*) FROM source_records WHERE source = :source")

_BATCH_ROWS = text("""
    SELECT sr.id, sr.source_id, sr.publication_year, sr.publication_date,
           sr.publication_date_precision::text AS precision, st.id AS staging_id, st.doi
    FROM source_records sr
    LEFT JOIN staging st ON st.id = sr.staging_id
    WHERE sr.source = :source AND sr.id > :after
    ORDER BY sr.id
    LIMIT :limit
""")

_WRITE = text("""
    UPDATE source_records sr
    SET publication_year = t.publication_year,
        publication_date = t.publication_date,
        publication_date_precision = CAST(t.publication_date_precision AS date_precision)
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(
        id integer, publication_year smallint, publication_date date,
        publication_date_precision text
    )
    WHERE sr.id = t.id
""")


def _rewrite_source(conn: Connection, source: str, *, dry_run: bool) -> None:
    total = conn.execute(_COUNT, {"source": source}).scalar_one()
    log.info("%s : %d enregistrements sources à traiter", source, total)
    normalizer = normalizer_builders(archive=False)[source](conn, log)
    store = get_raw_store()
    counts: Counter[str] = Counter()
    after = 0
    while rows := conn.execute(
        _BATCH_ROWS, {"source": source, "after": after, "limit": _BATCH}
    ).all():
        changed: list[dict[str, object]] = []
        year_changed: list[int] = []
        for r in rows:
            try:
                raw_data = json.loads(store.get(source, r.source_id))
            except KeyError, UnreadablePayloadError, ValueError:
                counts["sans payload"] += 1
                continue
            row = StagingRow(id=r.staging_id, source_id=r.source_id, doi=r.doi, raw_data=raw_data)
            doc = normalizer.parse(row)
            publication_date = normalizer.publication_date(doc) if doc is not None else None
            if publication_date is None:
                counts["sans date"] += 1
                continue
            columns = date_columns(publication_date)
            if (r.publication_date, r.precision) == (
                columns["publication_date"],
                columns["publication_date_precision"],
            ):
                counts["inchangée"] += 1
                continue
            counts[publication_date.precision.value] += 1
            changed.append({"id": r.id, **columns, "publication_date": str(publication_date.value)})
            if r.publication_year != publication_date.year:
                year_changed.append(r.id)
        counts["année changée"] += len(year_changed)
        if changed and not dry_run:
            conn.execute(_WRITE, {"rows": json.dumps(changed)})
            if year_changed:
                enqueue(
                    conn,
                    Queue.SOURCE_RECORD_KEYS,
                    "SELECT unnest(CAST(:ids AS integer[]))",
                    {"ids": year_changed},
                )
            conn.commit()
        after = rows[-1].id
        counts["traités"] += len(rows)
        log.info("%s : %d / %d traités", source, counts["traités"], total)
    log.info("%s : %s", source, dict(counts))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources",
        help="Sources à traiter, séparées par des virgules. Toutes par défaut, hors WoS.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compte les dates sans rien écrire")
    args = parser.parse_args()
    sources = (
        args.sources.split(",")
        if args.sources
        else [s.value for s in SOURCE_PRIORITY if s.value not in _EXCLUDED_SOURCES]
    )
    with get_sync_engine().connect() as conn:
        for source in sources:
            _rewrite_source(conn, source, dry_run=args.dry_run)
        if args.dry_run:
            log.info("Dry-run, rien écrit.")


if __name__ == "__main__":
    main()
