# STATUS: oneshot (2026-10-31)
"""Ramène les copies HAL du stock sur l'adresse de leur dépôt, comme l'écriture des localisations (`merge_locations`) : `https://hal.science/<identifiant sans version>`, quel que soit le portail. Les copies d'un même enregistrement source qui désignent un même dépôt se fusionnent. Idempotent.

Usage :
    uv run python -m interfaces.cli.oneshot.canonicalize_hal_location_urls [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import date

from sqlalchemy import text

from domain.publications.identifiers import hal_deposit_url
from domain.publications.licenses import License
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.ingestion.common.locations import LocationFacts, merge_locations

log = setup_logger("canonicalize_hal_location_urls", os.path.dirname(__file__))

_ROWS = text("""
    SELECT source_record_id, url, pdf_url, oai_id, version, license::text AS license, is_oa,
           platform_id, embargo_until
    FROM source_record_locations
    WHERE source_record_id IN (
        SELECT source_record_id FROM source_record_locations
        WHERE url ~* '(hal|archives-ouvertes|ccsd)'
    )
""")

_DELETE = text("DELETE FROM source_record_locations WHERE source_record_id = ANY(:ids)")

_INSERT = text("""
    INSERT INTO source_record_locations
        (source_record_id, url, pdf_url, oai_id, version, license, is_oa, platform_id,
         embargo_until)
    SELECT l.source_record_id, l.url, l.pdf_url, l.oai_id, l.version,
           CAST(l.license AS license_type), l.is_oa, l.platform_id, l.embargo_until
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS l(
        source_record_id integer, url text, pdf_url text, oai_id text, version text,
        license text, is_oa boolean, platform_id integer, embargo_until date
    )
""")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans rien écrire")
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        log.info("lecture des localisations des enregistrements sources à copie HAL…")
        by_record: dict[int, list] = defaultdict(list)
        for r in conn.execute(_ROWS):
            by_record[r.source_record_id].append(r)
        rows: list[dict] = []
        changed: list[int] = []
        for record_id, locations in by_record.items():
            if not any(hal_deposit_url(r.url) not in (None, r.url) for r in locations):
                continue
            # Plateforme d'une copie fusionnée : celle de la première localisation de même adresse.
            platforms: dict[str, int | None] = {}
            for r in locations:
                platforms.setdefault(hal_deposit_url(r.url) or r.url, r.platform_id)
            merged = merge_locations(
                LocationFacts(
                    url=r.url,
                    pdf_url=r.pdf_url,
                    oai_id=r.oai_id,
                    version=r.version,
                    license=License(r.license) if r.license else None,
                    is_oa=r.is_oa,
                    embargo_until=r.embargo_until,
                )
                for r in locations
            )
            changed.append(record_id)
            rows += [
                {
                    "source_record_id": record_id,
                    "url": loc.url,
                    "pdf_url": loc.pdf_url,
                    "oai_id": loc.oai_id,
                    "version": loc.version,
                    "license": loc.license.value if loc.license else None,
                    "is_oa": loc.is_oa,
                    "platform_id": platforms.get(loc.url),
                    "embargo_until": loc.embargo_until.isoformat()
                    if isinstance(loc.embargo_until, date)
                    else None,
                }
                for loc in merged
            ]
        if changed:
            conn.execute(_DELETE, {"ids": changed})
            conn.execute(_INSERT, {"rows": json.dumps(rows)})
        log.info("%d enregistrements sources aux copies HAL réécrites", len(changed))
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
