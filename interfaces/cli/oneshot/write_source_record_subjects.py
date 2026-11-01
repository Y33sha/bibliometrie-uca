# STATUS: oneshot (2026-11-01)
"""Écrit les sujets des enregistrements sources OpenAlex et ScanR déjà normalisés, lus dans le payload du raw store.

Seuls les enregistrements sources sans sujet sont lus : un passage interrompu reprend où il s'est arrêté. Un enregistrement source sans payload au raw store reste sans sujet.

Usage :
    uv run python -m interfaces.cli.oneshot.write_source_record_subjects [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Callable, Mapping

from sqlalchemy import Connection, text

from domain.subjects.subject import SubjectLink
from domain.types import JsonValue, as_mapping
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store import UnreadablePayloadError, get_raw_store
from pipeline.ingestion.common.subjects import SourceRecordSubjectStore
from pipeline.ingestion.openalex.normalize import get_subjects as openalex_subjects
from pipeline.ingestion.scanr.payload import scanr_subjects

log = setup_logger("write_source_record_subjects", os.path.dirname(__file__))

_BATCH = 1000

_SUBJECTS_OF_PAYLOAD: dict[str, Callable[[Mapping[str, JsonValue]], list[SubjectLink]]] = {
    "openalex": openalex_subjects,
    "scanr": lambda payload: scanr_subjects(payload.get("domains")),
}

_WITHOUT_SUBJECTS = """
    sr.source = CAST(:source AS source_type)
    AND NOT EXISTS (SELECT 1 FROM source_record_subjects srs WHERE srs.source_record_id = sr.id)
"""

_COUNT = text(f"SELECT count(*) FROM source_records sr WHERE {_WITHOUT_SUBJECTS}")

_BATCH_ROWS = text(f"""
    SELECT sr.id, sr.source_id
    FROM source_records sr
    WHERE {_WITHOUT_SUBJECTS} AND sr.id > :after
    ORDER BY sr.id
    LIMIT :limit
""")


def _write(conn: Connection, source: str, *, dry_run: bool) -> None:
    subjects_of_payload = _SUBJECTS_OF_PAYLOAD[source]
    total = conn.execute(_COUNT, {"source": source}).scalar_one()
    log.info("%s : %d enregistrements sources sans sujet", source, total)
    store = SourceRecordSubjectStore(conn)
    raw_store = get_raw_store()
    counts: Counter[str] = Counter()
    after = 0
    while rows := conn.execute(
        _BATCH_ROWS, {"source": source, "after": after, "limit": _BATCH}
    ).all():
        links_by_source_record: dict[int, list[SubjectLink]] = {}
        for row in rows:
            try:
                payload = json.loads(raw_store.get(source, row.source_id))
            except KeyError, UnreadablePayloadError, ValueError:
                counts["sans payload"] += 1
                continue
            links = subjects_of_payload(as_mapping(payload))
            counts["avec sujets" if links else "sans sujet"] += 1
            links_by_source_record[row.id] = links
        if links_by_source_record and not dry_run:
            store.replace_subjects_bulk(links_by_source_record)
            conn.commit()
        after = rows[-1].id
        counts["traités"] += len(rows)
        log.info("%s : %d / %d traités", source, counts["traités"], total)
    log.info("%s : %s", source, dict(counts))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte les sujets sans rien écrire")
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        for source in _SUBJECTS_OF_PAYLOAD:
            _write(conn, source, dry_run=args.dry_run)
        if args.dry_run:
            log.info("Dry-run, rien écrit.")


if __name__ == "__main__":
    main()
