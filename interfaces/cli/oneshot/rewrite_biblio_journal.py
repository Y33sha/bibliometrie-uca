# STATUS: oneshot (2026-10-31)
"""Réécrit `biblio.journal` des enregistrements sources déjà normalisés : la série qui sert au rattachement, ISSN en liste avec leur support.

Le payload de chaque enregistrement source est relu au raw store. Le normaliseur de sa source en tire la description du conteneur, puis la série (`determine_container_type`). Seul `biblio.journal` est réécrit. Un enregistrement source sans payload au raw store garde sa série, convertie en SQL : ISSN, ISSN électronique et ISSN-L passent dans la liste, sans support pour l'ISSN.

Usage :
    uv run python -m interfaces.cli.oneshot.rewrite_biblio_journal [--sources hal,openalex] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import Connection, text

from domain.serials.containers import determine_container_type
from domain.source_records.biblio import with_journal
from domain.sources.registry import SOURCE_PRIORITY
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store import UnreadablePayloadError, get_raw_store
from pipeline.ingestion.common.normalize import normalizer_builders
from pipeline.ingestion.common.staging import StagingRow

log = setup_logger("rewrite_biblio_journal", os.path.dirname(__file__))

_BATCH = 1000

_COUNT = text("SELECT count(*) FROM source_records WHERE source = :source")

_BATCH_ROWS = text("""
    SELECT sr.id, sr.source_id, sr.biblio, st.id AS staging_id, st.doi
    FROM source_records sr
    LEFT JOIN staging st ON st.id = sr.staging_id
    WHERE sr.source = :source AND sr.id > :after
    ORDER BY sr.id
    LIMIT :limit
""")

_WRITE = text("""
    UPDATE source_records sr SET biblio = t.biblio
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(id integer, biblio jsonb)
    WHERE sr.id = t.id AND sr.biblio IS DISTINCT FROM t.biblio
""")

# Série à l'ancienne forme (`issn`, `eissn`, `issnl`) convertie en liste d'ISSN, pour les enregistrements sources sans payload.
_CONVERT_LEGACY = text("""
    UPDATE source_records sr
    SET biblio = jsonb_set(
        sr.biblio, '{journal}',
        (sr.biblio->'journal') - 'issn' - 'eissn' - 'issnl'
        || jsonb_build_object('issns', (
            SELECT coalesce(jsonb_agg(v.item), '[]'::jsonb)
            FROM (VALUES
                (CASE WHEN sr.biblio->'journal' ? 'issn'
                      THEN jsonb_build_object('issn', sr.biblio->'journal'->>'issn') END),
                (CASE WHEN sr.biblio->'journal' ? 'eissn'
                      THEN jsonb_build_object('issn', sr.biblio->'journal'->>'eissn',
                                              'support', 'electronic') END),
                (CASE WHEN sr.biblio->'journal' ? 'issnl'
                      THEN jsonb_build_object('issn', sr.biblio->'journal'->>'issnl',
                                              'linking', true) END)
            ) AS v(item)
            WHERE v.item IS NOT NULL
        ))
    )
    WHERE sr.source = :source
      AND sr.biblio->'journal' ?| array['issn', 'eissn', 'issnl']
""")


def _rewrite_source(conn: Connection, source: str) -> None:
    total = conn.execute(_COUNT, {"source": source}).scalar_one()
    log.info("%s : %d enregistrements sources à traiter", source, total)
    normalizer = normalizer_builders(archive=False)[source](conn, log)
    store = get_raw_store()
    written = missing = refused = seen = 0
    after = 0
    while rows := conn.execute(
        _BATCH_ROWS, {"source": source, "after": after, "limit": _BATCH}
    ).all():
        batch: list[dict[str, object]] = []
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
            facts = normalizer.container_facts(doc)
            series, _ = determine_container_type(facts) if facts is not None else (None, None)
            batch.append({"id": r.id, "biblio": with_journal(r.biblio, series)})
        if batch:
            written += conn.execute(_WRITE, {"rows": json.dumps(batch)}).rowcount
        conn.commit()
        seen += len(rows)
        after = rows[-1].id
        log.info("%s : %d / %d traités", source, seen, total)
    converted = conn.execute(_CONVERT_LEGACY, {"source": source}).rowcount
    conn.commit()
    log.info(
        "%s : %d séries réécrites, %d converties sans payload au raw store (%d sans payload), %d refusées par la normalisation",
        source,
        written,
        converted,
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
                log.info(
                    "%s : %d enregistrements sources à traiter",
                    source,
                    conn.execute(_COUNT, {"source": source}).scalar_one(),
                )
            log.info("Dry-run, rien écrit.")
            return
        for source in sources:
            _rewrite_source(conn, source)


if __name__ == "__main__":
    main()
