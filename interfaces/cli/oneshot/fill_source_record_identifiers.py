# STATUS: oneshot (2026-10-28)
"""Remplit `source_record_identifiers` pour les enregistrements sources déjà normalisés.

Chaque enregistrement source relit son payload au raw store. Le normaliseur de sa source en tire ses identifiants, que le script écrit seuls : le reste de l'enregistrement source est inchangé. Un enregistrement source sans ligne de `staging` ou sans payload au raw store est ignoré.

Usage :
    uv run python -m interfaces.cli.oneshot.fill_source_record_identifiers [--sources hal,openalex] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import Connection, text

from domain.source_records.identifiers import SourceIdentifier
from domain.sources.registry import SOURCE_PRIORITY
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store import UnreadablePayloadError, get_raw_store
from pipeline.ingestion.common.normalize import normalizer_builders
from pipeline.ingestion.common.source_records import normalized_identifiers, replace_identifiers
from pipeline.ingestion.common.staging import StagingRow
from pipeline.transformation.publishing.find_or_create import Containers

log = setup_logger("fill_source_record_identifiers", os.path.dirname(__file__))

_BATCH = 1000

_COUNT = text("""
    SELECT count(*) FILTER (WHERE staging_id IS NOT NULL) AS staged,
           count(*) FILTER (WHERE staging_id IS NULL) AS unstaged
    FROM source_records WHERE source = :source
""")

_BATCH_ROWS = text("""
    SELECT sr.id, sr.source_id, st.id AS staging_id, st.doi
    FROM source_records sr
    JOIN staging st ON st.id = sr.staging_id
    WHERE sr.source = :source AND sr.id > :after
    ORDER BY sr.id
    LIMIT :limit
""")


def _fill_source(conn: Connection, source: str) -> None:
    staged, unstaged = conn.execute(_COUNT, {"source": source}).one()
    log.info("%s : %d enregistrements sources à traiter", source, staged)
    if unstaged:
        log.warning(
            "%s : %d enregistrements sources sans ligne de staging, ignorés", source, unstaged
        )
    normalizer = normalizer_builders(archive=False)[source](conn, log)
    store = get_raw_store()
    written = missing = refused = seen = 0
    after = 0
    while rows := conn.execute(
        _BATCH_ROWS, {"source": source, "after": after, "limit": _BATCH}
    ).all():
        batch: dict[int, tuple[SourceIdentifier, ...]] = {}
        for r in rows:
            try:
                raw_data = json.loads(store.get(source, r.source_id))
            except KeyError, UnreadablePayloadError, ValueError:
                missing += 1
                continue
            row = StagingRow(id=r.staging_id, source_id=r.source_id, doi=r.doi, raw_data=raw_data)
            doc = normalizer.parse(row)
            if doc is None:
                refused += 1
                continue
            record = normalizer.source_record(row, doc, Containers(None, None))
            batch[r.id] = normalized_identifiers(record)
        replace_identifiers(conn, batch)
        conn.commit()
        written += len(batch)
        seen += len(rows)
        after = rows[-1].id
        log.info("%s : %d / %d traités", source, seen, staged)
    log.info(
        "%s : identifiants écrits pour %d enregistrements sources, %d sans payload au raw store, %d refusés par la normalisation",
        source,
        written,
        missing,
        refused,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources",
        help="Sources à traiter, séparées par des virgules. Toutes par défaut.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compte les cibles sans rien écrire")
    args = parser.parse_args()
    sources = args.sources.split(",") if args.sources else [s.value for s in SOURCE_PRIORITY]
    with get_sync_engine().connect() as conn:
        if args.dry_run:
            for source in sources:
                staged, unstaged = conn.execute(_COUNT, {"source": source}).one()
                log.info(
                    "%s : %d enregistrements sources à traiter, %d sans ligne de staging",
                    source,
                    staged,
                    unstaged,
                )
            log.info("Dry-run, rien écrit.")
            return
        for source in sources:
            _fill_source(conn, source)


if __name__ == "__main__":
    main()
