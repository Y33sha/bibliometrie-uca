# STATUS: oneshot (2026-09-15)
"""Remet toutes les revues à vérifier dans le Sudoc.

Les règles de la vérification changent : support lu dans `183$a`, ISSN périmés rangés parmi les ISSN rejetés, liens d'autre support (`452`). Le prochain passage de la phase `publishers_journals` vérifie de nouveau toutes les revues, à partir de leurs ISSN actuels.

Usage :
    python -m interfaces.cli.oneshot.backfill_reset_sudoc_check            # exécution
    python -m interfaces.cli.oneshot.backfill_reset_sudoc_check --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_reset_sudoc_check", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        checked = conn.execute(
            text("SELECT count(*) FROM journals WHERE sudoc_checked_at IS NOT NULL")
        ).scalar_one()
        log.info("Revues vérifiées à remettre à vérifier : %d", checked)
        if args.dry_run:
            log.info("DRY-RUN terminé — aucune écriture")
            return 0
        conn.execute(
            text("UPDATE journals SET sudoc_checked_at = NULL WHERE sudoc_checked_at IS NOT NULL")
        )
        conn.commit()
        log.info("✓ backfill appliqué")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
