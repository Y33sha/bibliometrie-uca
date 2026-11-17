# STATUS: oneshot (2026-11-16)
"""Fait sortir du stock les publications d'errata et d'avis de rétractation, exclues des publications (`OUT_OF_SCOPE_DOC_TYPES`).

Passent en file de réconciliation les enregistrements sources des publications de type `erratum` ou `retraction`, et les enregistrements sources de ces types rattachés à une autre publication. La réconciliation détache les enregistrements sources d'erratum et d'avis. La publication d'un avis disparaît. Les autres enregistrements sources rejoignent la publication de leur œuvre.

Usage :
    uv run python -m interfaces.cli.oneshot.requeue_notice_publications [--dry-run]
    run_pipeline --from metadata_correction
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger

log = setup_logger("requeue_notice_publications", os.path.dirname(__file__))

_SOURCE_RECORDS = """
    SELECT sr.id FROM source_records sr
    JOIN publications p ON p.id = sr.publication_id
    WHERE p.doc_type IN ('erratum', 'retraction') OR sr.doc_type IN ('erratum', 'retraction')
"""

_COUNTS = text(f"""
    SELECT (SELECT count(*) FROM publications WHERE doc_type IN ('erratum', 'retraction')) AS publications,
           (SELECT count(*) FROM ({_SOURCE_RECORDS}) s) AS source_records
""")


def requeue(conn: Connection, *, dry_run: bool) -> None:
    """Marque pour la réconciliation les enregistrements sources des errata et des avis rattachés à une publication."""
    counts = conn.execute(_COUNTS).one()
    log.info(
        "Publications d'errata et d'avis : %d ; enregistrements sources à réconcilier : %d",
        counts.publications,
        counts.source_records,
    )
    if dry_run:
        return
    marked = enqueue(conn, Queue.SOURCE_RECORD_KEYS, _SOURCE_RECORDS, {})
    log.info("Marqués pour la réconciliation : %d", marked)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()
    with get_sync_engine().begin() as conn:
        requeue(conn, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
