# STATUS: oneshot (2026-09-15)
"""Remet à vérifier dans le Sudoc les revues qui ont des ISSN rejetés valides.

La vérification Sudoc réexamine les ISSN rejetés valides avec ses règles actuelles. Un ISSN rejeté par une règle antérieure retrouve sa colonne quand le Sudoc le rattache à la revue.

Usage :
    python -m interfaces.cli.oneshot.backfill_recheck_rejected_issns             # applique
    python -m interfaces.cli.oneshot.backfill_recheck_rejected_issns --dry-run   # rapport seul
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_recheck_rejected_issns", os.path.dirname(__file__))

_WITH_VALID_REJECTED = (
    "sudoc_checked_at IS NOT NULL AND EXISTS ("
    "SELECT 1 FROM unnest(rejected_issns) v WHERE v ~ '^[0-9]{4}-[0-9]{3}[0-9X]$')"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        count = conn.execute(
            text(f"SELECT count(*) FROM journals WHERE {_WITH_VALID_REJECTED}")
        ).scalar_one()
        log.info("Revues à remettre à vérifier : %d", count)
        if args.dry_run:
            log.info("DRY-RUN terminé — aucune écriture")
            return 0
        conn.execute(
            text(f"UPDATE journals SET sudoc_checked_at = NULL WHERE {_WITH_VALID_REJECTED}")
        )
        conn.commit()
        log.info("✓ backfill appliqué")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
