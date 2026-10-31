# STATUS: oneshot (2026-10-31)
"""Retire du stock le numéro de version des adresses de dépôt HAL des localisations HAL (`unversioned_hal_url`), comme la normalisation HAL. Idempotent.

Usage :
    uv run python -m interfaces.cli.oneshot.unversion_hal_location_urls [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.ingestion.hal.normalize import unversioned_hal_url

log = setup_logger("unversion_hal_location_urls", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans rien écrire")
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        log.info("lecture des localisations HAL…")
        rows = conn.execute(
            text("""
                SELECT l.source_record_id, l.url
                FROM source_record_locations l
                JOIN source_records sr ON sr.id = l.source_record_id AND sr.source = 'hal'
            """)
        ).all()
        changes = [
            {"id": r.source_record_id, "old": r.url, "new": new}
            for r in rows
            if (new := unversioned_hal_url(r.url)) != r.url
        ]
        if changes:
            conn.execute(
                text("""
                    UPDATE source_record_locations SET url = :new
                    WHERE source_record_id = :id AND url = :old
                """),
                changes,
            )
        log.info("%d adresses de dépôt HAL sans numéro de version", len(changes))
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
