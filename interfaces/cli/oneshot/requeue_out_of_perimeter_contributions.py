# STATUS: oneshot (2026-11-03)
"""Remet en file de résolution les contributions hors périmètre rattachées à une personne sans épinglage.

La décision rattache une contribution hors périmètre seulement par un identifiant d'attribution confirmée ou authentifiée (`decide_contribution`). La phase `persons` redécide les contributions remises en file :
    run_pipeline --from persons

Usage :
    uv run python -m interfaces.cli.oneshot.requeue_out_of_perimeter_contributions [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from domain.persons.contribution_matching import ContributionMatchReason
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger

log = setup_logger("requeue_out_of_perimeter_contributions", os.path.dirname(__file__))

_TARGETS = f"""
    SELECT id FROM contributions
    WHERE person_id IS NOT NULL AND NOT in_perimeter
      AND resolution_mode <> '{ContributionMatchReason.MANUAL}'
"""

_BY_MODE = text(f"""
    SELECT resolution_mode::text AS mode, count(*) AS n
    FROM contributions WHERE id IN ({_TARGETS})
    GROUP BY 1 ORDER BY 2 DESC
""")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="rapport seul, sans écriture")
    args = parser.parse_args()

    with get_sync_engine().begin() as conn:
        for r in conn.execute(_BY_MODE):
            log.info("%s : %d contributions", r.mode, r.n)
        if args.dry_run:
            return
        marked = enqueue(conn, Queue.CONTRIBUTION_RESOLUTION, _TARGETS, {})
        log.info("%d contributions remises en file", marked)


if __name__ == "__main__":
    main()
