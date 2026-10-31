# STATUS: oneshot (2026-10-30)
"""Retire du stock les localisations qui sont des pages descriptives (`is_descriptive_page`), comme l'écriture des localisations à la normalisation.

Les enregistrements sources qui perdent une localisation ouverte passent dans la file de réconciliation : la phase `publications` recalcule ensuite la meilleure copie de leur publication. Idempotent.

Usage :
    uv run python -m interfaces.cli.oneshot.purge_descriptive_page_locations [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from domain.platforms.platform import is_descriptive_page
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger

log = setup_logger("purge_descriptive_page_locations", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans rien écrire")
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        log.info("lecture des URL des localisations…")
        urls = [
            url
            for (url,) in conn.execute(text("SELECT DISTINCT url FROM source_record_locations"))
            if is_descriptive_page(url)
        ]
        deleted = conn.execute(
            text("""
                DELETE FROM source_record_locations
                WHERE url = ANY(:urls)
                RETURNING source_record_id, is_oa
            """),
            {"urls": urls},
        ).all()
        queued = enqueue(
            conn,
            Queue.SOURCE_RECORD_KEYS,
            "SELECT unnest(CAST(:ids AS int[]))",
            {"ids": sorted({r.source_record_id for r in deleted if r.is_oa})},
        )
        log.info(
            "%d localisations retirées (%d URL), %d enregistrements sources à réconcilier",
            len(deleted),
            len(urls),
            queued,
        )
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
