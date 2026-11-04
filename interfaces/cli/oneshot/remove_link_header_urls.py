# STATUS: oneshot (2026-11-03)
"""Retire du stock les adresses d'en-tête HTTP `Link` recopiées par OpenAlex comme localisations (`is_link_header_fragment`) : profils ORCID, pages de navigation d'entrepôts.

Les adresses sortent des `urls` des enregistrements sources OpenAlex, et des valeurs d'origine gardées par la correction unaire (`corrections.urls.raw`). Une localisation à adresse écartée prend celle de son PDF ; sans PDF, elle disparaît. Les enregistrements sources concernés passent en file de réconciliation : leur publication recalcule ses copies.

Usage :
    uv run python -m interfaces.cli.oneshot.remove_link_header_urls [--dry-run]
    run_pipeline --from metadata_correction
"""

from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import Connection, text

from domain.urls import is_link_header_fragment
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger

log = setup_logger("remove_link_header_urls", os.path.dirname(__file__))

_RECORDS = text("""
    SELECT id, urls, corrections -> 'urls' -> 'raw' AS raw_urls
    FROM source_records
    WHERE source = 'openalex'
      AND (array_to_string(urls, ' ') LIKE '%>%'
           OR (corrections -> 'urls' -> 'raw')::text LIKE '%>%')
""")

_UPDATE_RECORDS = text("""
    UPDATE source_records sr
    SET urls = CASE WHEN jsonb_array_length(d.urls) = 0 THEN NULL
                    ELSE ARRAY(SELECT jsonb_array_elements_text(d.urls)) END,
        corrections = CASE WHEN d.raw_urls IS NULL THEN sr.corrections
                           ELSE jsonb_set(sr.corrections, '{urls,raw}', d.raw_urls) END,
        updated_at = clock_timestamp()
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS d(id integer, urls jsonb, raw_urls jsonb)
    WHERE sr.id = d.id
""")

_LOCATIONS = text("""
    SELECT l.source_record_id, l.url, l.pdf_url
    FROM source_record_locations l
    JOIN source_records sr ON sr.id = l.source_record_id
    WHERE sr.source = 'openalex' AND l.url LIKE '%>%'
""")

_INSERT_PDF_LOCATIONS = text("""
    INSERT INTO source_record_locations
        (source_record_id, url, pdf_url, oai_id, version, license, is_oa, platform_id)
    SELECT l.source_record_id, l.pdf_url, l.pdf_url, l.oai_id, l.version, l.license, l.is_oa,
           l.platform_id
    FROM source_record_locations l
    JOIN jsonb_to_recordset(CAST(:rows AS jsonb)) AS d(source_record_id integer, url text)
      ON d.source_record_id = l.source_record_id AND d.url = l.url
    WHERE l.pdf_url IS NOT NULL
    ON CONFLICT (source_record_id, url) DO NOTHING
""")

_DELETE_LOCATIONS = text("""
    DELETE FROM source_record_locations l
    USING jsonb_to_recordset(CAST(:rows AS jsonb)) AS d(source_record_id integer, url text)
    WHERE l.source_record_id = d.source_record_id AND l.url = d.url
""")


def _kept(urls: list[str] | None) -> list[str]:
    return [u for u in urls or () if not is_link_header_fragment(u)]


def remove(conn: Connection, *, dry_run: bool) -> None:
    """Retire les adresses d'en-tête `Link` des enregistrements sources OpenAlex et de leurs localisations, et marque ces enregistrements sources pour la réconciliation."""
    records = []
    records_rows = []
    for r in conn.execute(_RECORDS):
        urls = _kept(r.urls)
        raw = _kept(r.raw_urls) if isinstance(r.raw_urls, list) else None
        if urls != list(r.urls or ()) or (raw is not None and raw != r.raw_urls):
            records.append({"id": r.id, "urls": urls, "raw_urls": raw})
            records_rows.append(r)
    fragments = [r for r in conn.execute(_LOCATIONS) if is_link_header_fragment(r.url)]
    locations = [{"source_record_id": r.source_record_id, "url": r.url} for r in fragments]
    with_pdf = sum(1 for r in fragments if r.pdf_url)
    log.info("Enregistrements sources à nettoyer : %d", len(records))
    log.info("Localisations à adresse écartée : %d, dont %d avec un PDF", len(locations), with_pdf)
    if dry_run:
        return
    conn.execute(_UPDATE_RECORDS, {"rows": json.dumps(records)})
    conn.execute(_INSERT_PDF_LOCATIONS, {"rows": json.dumps(locations)})
    conn.execute(_DELETE_LOCATIONS, {"rows": json.dumps(locations)})
    ids = sorted({r.id for r in records_rows} | {r.source_record_id for r in fragments})
    marked = enqueue(
        conn, Queue.SOURCE_RECORD_KEYS, "SELECT unnest(CAST(:ids AS integer[]))", {"ids": ids}
    )
    log.info("Marqués pour la réconciliation : %d", marked)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()
    with get_sync_engine().begin() as conn:
        remove(conn, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
