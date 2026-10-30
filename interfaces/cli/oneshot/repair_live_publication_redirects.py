# STATUS: oneshot (2026-10-15)
"""Supprime les redirections de publication dont l'identifiant absorbé désigne une publication présente en base.

Une telle redirection, auto-redirection comprise, fait échouer la dissolution suivante de la même publication par la réconciliation.

Usage :
    uv run python -m interfaces.cli.oneshot.repair_live_publication_redirects [--dry-run]
"""

import argparse
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("repair_live_publication_redirects", os.path.dirname(__file__))

_LIVE = """
    r.entity = 'publication'
    AND EXISTS (SELECT 1 FROM publications p WHERE p.id = r.absorbed_id)
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Redirections de publication vivante")
    parser.add_argument("--dry-run", action="store_true", help="Liste sans supprimer")
    args = parser.parse_args()
    with get_sync_engine().begin() as conn:
        rows = conn.execute(
            text(f"SELECT r.absorbed_id, r.kept_id FROM merge_redirects r WHERE {_LIVE} ORDER BY 1")
        ).all()
        for row in rows:
            log.info("publication %d → %d", row.absorbed_id, row.kept_id)
        if args.dry_run:
            log.info("%d redirections à supprimer (dry-run)", len(rows))
            return
        deleted = conn.execute(text(f"DELETE FROM merge_redirects r WHERE {_LIVE}")).rowcount
        log.info("%d redirections supprimées", deleted)


if __name__ == "__main__":
    main()
