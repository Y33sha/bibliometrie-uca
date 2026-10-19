# STATUS: oneshot (2026-10-19)
"""Supprime les signatures du stock dont le nom tient lieu de nom absent (« (:Unap) », « None, None »), comme le fait la normalisation (`is_placeholder_name`).

Les décomptes d'auteurs des notices touchées sont recalculés et leurs publications sont à regrouper. Les identités devenues orphelines sont supprimées. La phase `persons` purge les personnes vidées.

Usage :
    python -m interfaces.cli.oneshot.delete_placeholder_author_names [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from domain.persons.signature_name import is_placeholder_name
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from interfaces.cli.oneshot.backfill_author_counts import backfill_notices
from interfaces.cli.oneshot.decode_latex_author_names import candidates_sql
from pipeline.ingestion.common.signature_queries import delete_orphan_identities

log = setup_logger("delete_placeholder_author_names", os.path.dirname(__file__))

CANDIDATES_SQL = candidates_sql("n.names ~* '(:|none|null)'")

_MARK_DIRTY_SQL = text("""
    UPDATE publications p SET authorships_dirty = true
    FROM source_publications sp
    WHERE sp.id = ANY(:notices) AND p.id = sp.publication_id AND NOT p.authorships_dirty
""")


def placeholder_signatures(conn: Connection) -> tuple[list[int], list[int]]:
    """Signatures dont le nom stocké tient lieu de nom absent, et leurs notices."""
    ids: list[int] = []
    notices: set[int] = set()
    for r in conn.execute(CANDIDATES_SQL):
        name = (
            f"{r.raw_last_name} {r.raw_first_name or ''}"
            if r.raw_last_name is not None
            else r.raw_author_name or ""
        )
        if is_placeholder_name(name):
            ids.append(r.id)
            notices.add(r.notice)
    return ids, sorted(notices)


def delete(conn: Connection, ids: list[int], notices: list[int]) -> int:
    """Supprime les signatures, met à jour les notices et les publications. Rend le nombre d'identités orphelines supprimées."""
    conn.execute(text("DELETE FROM source_authorships WHERE id = ANY(:ids)"), {"ids": ids})
    backfill_notices(conn, notices)
    conn.execute(_MARK_DIRTY_SQL, {"notices": notices})
    return delete_orphan_identities(conn)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        ids, notices = placeholder_signatures(conn)
        log.info("signatures à supprimer : %d, dans %d notices", len(ids), len(notices))
        if args.dry_run or not ids:
            conn.rollback()
            return 0
        orphans = delete(conn, ids, notices)
        conn.commit()
        log.info(
            "signatures supprimées : %d ; identités orphelines supprimées : %d", len(ids), orphans
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
