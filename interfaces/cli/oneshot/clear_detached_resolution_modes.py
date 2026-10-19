# STATUS: oneshot (2026-10-19)
"""Retire le mode de résolution des signatures sans personne.

Les détachements de l'administration (rejet d'une paire, détachement par forme de nom) laissaient le mode de résolution sur la signature détachée.

Usage :
    python -m interfaces.cli.oneshot.clear_detached_resolution_modes [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("clear_detached_resolution_modes", os.path.dirname(__file__))

_WHERE = "person_id IS NULL AND resolution_mode IS NOT NULL"


def clear(conn: Connection) -> int:
    """Retire le mode de résolution des signatures sans personne. Rend le nombre de signatures modifiées."""
    return conn.execute(
        text(f"UPDATE source_authorships SET resolution_mode = NULL WHERE {_WHERE}")
    ).rowcount


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        count = conn.execute(
            text(f"SELECT count(*) FROM source_authorships WHERE {_WHERE}")
        ).scalar_one()
        log.info("signatures sans personne avec un mode de résolution : %d", count)
        if args.dry_run or not count:
            conn.rollback()
            return 0
        cleared = clear(conn)
        conn.commit()
        log.info("modes de résolution retirés : %d", cleared)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
