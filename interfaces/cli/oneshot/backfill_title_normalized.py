# STATUS: oneshot (2026-06-15)
"""Backfill de `source_publications.title_normalized` sur le stock existant.

Les upserts du `normalize` remplissent désormais `title_normalized` au même mouvement que
`title`, mais les SP déjà en base ont la colonne `NULL`. Ce one-shot la calcule
(`domain.publications.metadata.normalized_title`) pour toutes les SP `title_normalized IS NULL`.
`title` étant INSERT-only, le backfill est définitif (pas de recompute à entretenir).

Usage :
    python -m interfaces.cli.oneshot.backfill_title_normalized [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from domain.publications.metadata import normalized_title
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_title_normalized", os.path.dirname(__file__))

BATCH = 5000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Compte les SP à backfiller et sort."
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        if args.dry_run:
            n = conn.execute(
                text("SELECT count(*) FROM source_publications WHERE title_normalized IS NULL")
            ).scalar_one()
            log.info("DRY-RUN : %d source_publications à backfiller", n)
            return 0

        total = 0
        while True:
            rows = conn.execute(
                text(
                    "SELECT id, title FROM source_publications "
                    "WHERE title_normalized IS NULL LIMIT :lim"
                ),
                {"lim": BATCH},
            ).all()
            if not rows:
                break
            conn.execute(
                text("UPDATE source_publications SET title_normalized = :tn WHERE id = :id"),
                [{"id": r.id, "tn": normalized_title(r.title)} for r in rows],
            )
            conn.commit()
            total += len(rows)
            log.info("  %d backfillés...", total)
        log.info("✓ %d title_normalized backfillés", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
