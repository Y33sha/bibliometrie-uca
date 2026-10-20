# STATUS: oneshot (2026-10-19)
"""Marque à regrouper les publications dont les groupes d'auteurs ont pu s'appuyer sur un identifiant neutralisé.

Visées : les publications à plusieurs notices dont une signature neutralise son ORCID ou son IdRef. Elles reçoivent `contributions_dirty`, et la phase `author_grouping` recalcule leurs groupes au run suivant.

Usage :
    python -m interfaces.cli.oneshot.regroup_neutralized_identifiers [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("regroup_neutralized_identifiers", os.path.dirname(__file__))

_TARGETS = """
    SELECT DISTINCT sr.publication_id
    FROM source_contributions sc
    JOIN source_records sr ON sr.id = sc.source_record_id
    WHERE sr.publication_id IS NOT NULL
      AND sc.neutralized_identifiers ?| array['orcid', 'idref']
      AND EXISTS (
          SELECT 1 FROM source_records o
          WHERE o.publication_id = sr.publication_id AND o.id <> sr.id
      )
"""

_COUNT_SQL = text(f"""
    SELECT count(*) AS cibles, count(*) FILTER (WHERE NOT p.contributions_dirty) AS a_marquer
    FROM publications p WHERE p.id IN ({_TARGETS})
""")

_MARK_DIRTY_SQL = text(f"""
    UPDATE publications p SET contributions_dirty = true
    WHERE p.id IN ({_TARGETS}) AND NOT p.contributions_dirty
""")


def mark(conn: Connection) -> int:
    """Marque les publications visées. Rend le nombre de publications marquées."""
    return conn.execute(_MARK_DIRTY_SQL).rowcount


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        counts = conn.execute(_COUNT_SQL).one()
        log.info("publications visées : %d, dont %d à marquer", counts.cibles, counts.a_marquer)
        if args.dry_run or not counts.a_marquer:
            conn.rollback()
            return 0
        marked = mark(conn)
        conn.commit()
        log.info("publications marquées à regrouper : %d", marked)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
