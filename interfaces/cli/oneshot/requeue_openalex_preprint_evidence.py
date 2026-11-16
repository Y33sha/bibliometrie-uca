# STATUS: oneshot (2026-11-16)
"""Met en file de recomposition les contributions dont un indice d'affiliation vient d'un enregistrement OpenAlex non éditeur.

Seules sont marquées les contributions qui ont aussi une contribution source dans l'enregistrement OpenAlex éditeur, au DOI de la publication (`openalex_publisher_records`). La recomposition de leurs attributs écarte alors ces indices (`propagate_contribution_attributes_sql`). La phase `author_grouping` traite la file :
    run_pipeline --from author_grouping

Usage :
    uv run python -m interfaces.cli.oneshot.requeue_openalex_preprint_evidence [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from domain.sources.registry import Source
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue_sql
from infrastructure.observability.log import setup_logger
from infrastructure.sql_fragments import AFFILIATION_EVIDENCE_SQL, openalex_publisher_records

log = setup_logger("requeue_openalex_preprint_evidence", os.path.dirname(__file__))

_TARGETS = f"""
    WITH openalex AS (
        SELECT gm.contribution_id, gm.source_record_id, sc.perimeter_evidence
        FROM aligned_source_contributions gm
        JOIN source_contributions sc ON sc.id = gm.source_contribution_id
        WHERE sc.source = '{Source.OPENALEX}' AND gm.contribution_id IN (
            SELECT gm2.contribution_id FROM aligned_source_contributions gm2
            JOIN source_contributions sc2 ON sc2.id = gm2.source_contribution_id
            WHERE sc2.source = '{Source.OPENALEX}' AND sc2.perimeter_evidence && {AFFILIATION_EVIDENCE_SQL}
        )
    ),
    publishers AS ({openalex_publisher_records("SELECT id FROM publications")})
    SELECT DISTINCT o.contribution_id
    FROM openalex o
    WHERE o.perimeter_evidence && {AFFILIATION_EVIDENCE_SQL}
      AND o.source_record_id NOT IN (SELECT id FROM publishers)
      AND EXISTS (
          SELECT 1 FROM openalex p
          WHERE p.contribution_id = o.contribution_id AND p.source_record_id IN (SELECT id FROM publishers)
      )
"""
"""Contributions à indice d'affiliation d'un enregistrement OpenAlex non éditeur, et à contribution source dans l'enregistrement OpenAlex éditeur."""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="rapport seul, sans écriture")
    args = parser.parse_args()
    with get_sync_engine().begin() as conn:
        targets = conn.execute(text(f"SELECT count(*) FROM ({_TARGETS}) t")).scalar_one()
        log.info("%d contributions à recomposer", targets)
        if args.dry_run:
            conn.rollback()
            return
        marked = conn.execute(text(enqueue_sql(Queue.CONTRIBUTION_ATTRIBUTES, _TARGETS))).rowcount
        log.info("%d contributions marquées pour la recomposition de leurs attributs", marked)
        log.info("Ensuite : run_pipeline --from author_grouping")


if __name__ == "__main__":
    main()
