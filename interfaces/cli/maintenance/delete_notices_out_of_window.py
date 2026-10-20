# STATUS: maintenance
"""Supprime les notices parues avant l'année de début du pipeline (`config.pipeline_start_year_full`), avec leur ligne de `staging`. Les notices de theses.fr restent : ce moissonnage couvre tout l'historique des établissements.

Les notices sœurs sont marquées à réconcilier (`delete_source_records_before`). Le pipeline supprime ensuite les publications vidées (phase `publications`), puis les personnes vidées (phase `persons`).

Usage :
    python -m interfaces.cli.maintenance.delete_notices_out_of_window [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.db.scalars import scalar_int
from infrastructure.observability.log import setup_logger
from pipeline.ingestion.common.source_records import delete_source_records_before

log = setup_logger("delete_notices_out_of_window", os.path.dirname(__file__))

EXEMPT_SOURCES = ("theses",)


def fetch_cutoff(conn: Connection) -> int:
    """Année de début du pipeline (`config.pipeline_start_year_full`)."""
    return scalar_int(
        conn.execute(
            text("SELECT (value #>> '{}')::int FROM config WHERE key = 'pipeline_start_year_full'")
        )
    )


def count_targets(conn: Connection, cutoff: int) -> dict[str, int]:
    """Notices parues avant `cutoff`, par source, hors `EXEMPT_SOURCES`."""
    rows = conn.execute(
        text("""
            SELECT source::text, count(*) FROM source_records
            WHERE publication_year < :cutoff AND source::text <> ALL(:exempt)
            GROUP BY 1 ORDER BY 2 DESC
        """),
        {"cutoff": cutoff, "exempt": list(EXEMPT_SOURCES)},
    ).all()
    return dict(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="N'écrit rien : affiche les notices visées par source et sort.",
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        cutoff = fetch_cutoff(conn)
        targets = count_targets(conn, cutoff)
    log.info("Notices parues avant %d : %d", cutoff, sum(targets.values()))
    for source, n in targets.items():
        log.info("  %s : %d", source, n)
    if not targets or args.dry_run:
        return 0

    with engine.begin() as conn:
        deleted, staged = delete_source_records_before(conn, cutoff, exempt_sources=EXEMPT_SOURCES)
    log.info("Supprimées : %d notices, %d lignes de staging", deleted, staged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
