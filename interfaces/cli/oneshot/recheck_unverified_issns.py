# STATUS: oneshot (2026-11-09)
"""Remet en vérification Sudoc les ISSN `unverified`.

La vérification lisait seulement les notices Sudoc avec exemplaires en bibliothèque. Un ISSN dont la notice est sans exemplaire est donc resté `unverified`. Le oneshot vide `sudoc_checked_at` de ces ISSN, et la phase `publishing` les vérifie au run suivant.

Usage :
    uv run python -m interfaces.cli.oneshot.recheck_unverified_issns [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("recheck_unverified_issns", os.path.dirname(__file__))

_COUNT = text("SELECT count(*) FROM serial_issns WHERE status = 'unverified'")

_RESET = text("""
    UPDATE serial_issns SET sudoc_checked_at = NULL
    WHERE status = 'unverified' AND sudoc_checked_at IS NOT NULL
""")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte les ISSN sans rien écrire")
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        log.info("%d ISSN unverified", conn.execute(_COUNT).scalar_one())
        if args.dry_run:
            log.info("Dry-run, rien écrit.")
            return
        reset = conn.execute(_RESET).rowcount
        conn.commit()
        log.info("%d ISSN remis en vérification Sudoc", reset)


if __name__ == "__main__":
    main()
