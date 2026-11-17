# STATUS: oneshot (2026-11-17)
"""Applique au stock l'arbitrage du type `other` : `other` cède au premier type précis d'une source non agrégatrice (`_arbitrate_doc_type_with_article_subtype`).

La règle change seulement le type des publications de type `other`. Elles passent en file de consolidation.

Usage :
    uv run python -m interfaces.cli.oneshot.requeue_other_publications [--dry-run]
    run_pipeline --from publications
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger

log = setup_logger("requeue_other_publications", os.path.dirname(__file__))

_PUBLICATIONS = "SELECT id FROM publications WHERE doc_type = 'other'"


def requeue(conn: Connection, *, dry_run: bool) -> None:
    """Marque pour la consolidation les publications de type `other`."""
    count = conn.execute(text(f"SELECT count(*) FROM ({_PUBLICATIONS}) p")).scalar_one()
    log.info("Publications de type other : %d", count)
    if dry_run:
        return
    marked = enqueue(conn, Queue.PUBLICATIONS, _PUBLICATIONS, {})
    log.info("Marquées pour la consolidation : %d", marked)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()
    with get_sync_engine().begin() as conn:
        requeue(conn, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
