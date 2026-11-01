# STATUS: oneshot (2026-11-01)
"""Écrit les sujets des enregistrements sources déjà normalisés, avant la première dérivation de `publication_subjects`.

HAL et ScanR lisent leurs sujets dans `source_records.topics`, qui garde le code des domaines HAL et le PPN des vedettes RAMEAU de ScanR. OpenAlex les lit dans le payload du raw store : `topics` garde les libellés sans les identifiants. Un enregistrement source OpenAlex sans payload au raw store reste sans sujet. Les thèses reçoivent leurs sujets au remoissonnage de theses.fr.

Usage :
    uv run python -m interfaces.cli.oneshot.write_source_record_subjects [--sources hal,scanr,openalex] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Callable

from sqlalchemy import Connection, Row, text

from domain.sources.hal import hal_domain_subject
from domain.subjects.subject import SubjectLink
from domain.types import as_mapping, as_strs
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store import UnreadablePayloadError, get_raw_store
from pipeline.ingestion.common.subjects import SourceRecordSubjectStore
from pipeline.ingestion.openalex.normalize import get_subjects as openalex_subjects
from pipeline.ingestion.scanr.payload import scanr_subjects

log = setup_logger("write_source_record_subjects", os.path.dirname(__file__))

_BATCH = 1000
_SOURCES = ("hal", "scanr", "openalex")

_COUNT = text("SELECT count(*) FROM source_records WHERE source = CAST(:source AS source_type)")

_BATCH_ROWS = text("""
    SELECT id, source_id, topics
    FROM source_records
    WHERE source = CAST(:source AS source_type) AND id > :after
    ORDER BY id
    LIMIT :limit
""")


def _hal_links(row: Row) -> list[SubjectLink] | None:
    entries = as_strs(as_mapping(row.topics).get("hal_domains"))
    return [SubjectLink(subject) for entry in entries if (subject := hal_domain_subject(entry))]


def _scanr_links(row: Row) -> list[SubjectLink] | None:
    return scanr_subjects(row.topics)


def _openalex_links(row: Row) -> list[SubjectLink] | None:
    """Renvoie les topics du payload au raw store, ou `None` sans payload lisible."""
    try:
        work = json.loads(get_raw_store().get("openalex", row.source_id))
    except KeyError, UnreadablePayloadError, ValueError:
        return None
    return openalex_subjects(as_mapping(work))


_READERS: dict[str, Callable[[Row], list[SubjectLink] | None]] = {
    "hal": _hal_links,
    "scanr": _scanr_links,
    "openalex": _openalex_links,
}


def _write_source(conn: Connection, source: str, *, dry_run: bool) -> None:
    total = conn.execute(_COUNT, {"source": source}).scalar_one()
    log.info("%s : %d enregistrements sources à traiter", source, total)
    store = SourceRecordSubjectStore(conn)
    read = _READERS[source]
    counts: Counter[str] = Counter()
    after = 0
    while rows := conn.execute(
        _BATCH_ROWS, {"source": source, "after": after, "limit": _BATCH}
    ).all():
        links_by_source_record: dict[int, list[SubjectLink]] = {}
        for row in rows:
            links = read(row)
            if links is None:
                counts["sans payload"] += 1
                continue
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
    parser.add_argument(
        "--sources",
        help=f"Sources à traiter, séparées par des virgules. Par défaut : {', '.join(_SOURCES)}.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compte les sujets sans rien écrire")
    args = parser.parse_args()
    sources = args.sources.split(",") if args.sources else list(_SOURCES)
    with get_sync_engine().connect() as conn:
        for source in sources:
            _write_source(conn, source, dry_run=args.dry_run)
        if args.dry_run:
            log.info("Dry-run, rien écrit.")


if __name__ == "__main__":
    main()
