# STATUS: oneshot (2026-11-19)
"""Vide les pays des enregistrements sources sans contribution source, et marque leur publication pour la consolidation.

Les pays d'un enregistrement source réunissent ceux de ses contributions sources. Le stock contient des enregistrements sources OpenAlex privés de leurs contributions sources par `SourceContributionStore.withhold_source_contributions`, avec leurs pays.

Usage :
    uv run python -m interfaces.cli.oneshot.clear_countries_without_contributions [--dry-run]
    run_pipeline --from publications
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger

log = setup_logger("clear_countries_without_contributions", os.path.dirname(__file__))

_STALE = """
    SELECT sr.id, sr.publication_id FROM source_records sr
    WHERE sr.countries IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM source_contributions sc WHERE sc.source_record_id = sr.id)
"""


def clear(conn: Connection, *, dry_run: bool) -> None:
    """Vide les pays des enregistrements sources sans contribution source, et marque leur publication pour la consolidation."""
    count = conn.execute(text(f"SELECT count(*) FROM ({_STALE}) s")).scalar_one()
    log.info("Enregistrements sources à pays sans contribution source : %d", count)
    if dry_run:
        return
    marked = enqueue(
        conn,
        Queue.PUBLICATIONS,
        f"SELECT publication_id FROM ({_STALE}) s WHERE publication_id IS NOT NULL",
        {},
    )
    log.info("Publications marquées pour la consolidation : %d", marked)
    cleared = conn.execute(
        text(
            f"UPDATE source_records SET countries = NULL WHERE id IN (SELECT id FROM ({_STALE}) s)"
        )
    ).rowcount
    log.info("Enregistrements sources aux pays vidés : %d", cleared)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()
    with get_sync_engine().begin() as conn:
        clear(conn, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
