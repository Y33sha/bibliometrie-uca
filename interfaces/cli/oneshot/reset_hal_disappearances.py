# STATUS: oneshot (2026-11-01)
"""Retire la marque de disparition des dépôts HAL, pour que la relecture suivante les traite.

La relecture lit un dépôt par `find_deposit` : un doublon absorbé donne le dépôt conservé, et seule une page de dépôt absente (404) confirme l'absence.

Usage :
    uv run python -m interfaces.cli.oneshot.reset_hal_disappearances [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("reset_hal_disappearances", os.path.dirname(__file__))

_COUNT = text("SELECT count(*) FROM staging WHERE source = 'hal' AND disappeared_at IS NOT NULL")

_RESET = text(
    "UPDATE staging SET disappeared_at = NULL WHERE source = 'hal' AND disappeared_at IS NOT NULL"
)


def reset_hal_disappearances(conn: Connection, *, dry_run: bool = False) -> int:
    """Retire la marque de disparition des dépôts HAL. Renvoie leur nombre."""
    if dry_run:
        return int(conn.execute(_COUNT).scalar_one())
    return conn.execute(_RESET).rowcount


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte sans rien écrire")
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        count = reset_hal_disappearances(conn, dry_run=args.dry_run)
        log.info("Dépôts HAL marqués disparus : %d", count)
        if args.dry_run:
            log.info("Dry-run, rien écrit.")
        else:
            conn.commit()


if __name__ == "__main__":
    main()
