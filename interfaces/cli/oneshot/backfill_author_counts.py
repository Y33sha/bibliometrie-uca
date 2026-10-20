# STATUS: oneshot (2026-10-18)
"""Calcule `author_count` et `distinct_author_count` des notices du stock d'après leurs signatures en base, comme la normalisation (`is_individual_author`).

Les notices se traitent par lots d'identifiants, un commit par lot. Seules les valeurs qui changent s'écrivent. Idempotent.

Usage :
    python -m interfaces.cli.oneshot.backfill_author_counts [--dry-run] [--batch 50000]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from domain.publications.contribution_roles import ContributionRole
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_author_counts", os.path.dirname(__file__))

# Signature d'auteur individuelle, comme `is_individual_author`.
_AUTHOR = f"NOT sa.collective AND '{ContributionRole.AUTHOR.value}' = ANY(sa.roles)"


def _update_counts(conn: Connection, source_records: str, params: dict[str, object]) -> int:
    """Écrit les décomptes des notices filtrées par la condition SQL `notices` (sur `sp`) qui changent. Rend le nombre de notices modifiées."""
    return conn.execute(
        text(f"""
            UPDATE source_records sp
            SET author_count = c.n, distinct_author_count = c.d
            FROM (
                SELECT sp.id,
                       count(sa.id) FILTER (WHERE {_AUTHOR}) AS n,
                       count(DISTINCT (k.last_name_normalized, coalesce(k.first_name_normalized, '')))
                           FILTER (WHERE {_AUTHOR}) AS d
                FROM source_records sp
                LEFT JOIN source_contributions sa ON sa.source_record_id = sp.id
                LEFT JOIN contributor_information k ON k.id = sa.contributor_information_id
                WHERE {source_records}
                GROUP BY sp.id
            ) c
            WHERE sp.id = c.id AND (sp.author_count, sp.distinct_author_count) IS DISTINCT FROM (c.n, c.d)
        """),  # noqa: S608
        params,
    ).rowcount


def backfill_batch(conn: Connection, lo: int, hi: int) -> int:
    """Écrit les décomptes des notices `[lo, hi]` qui changent. Rend le nombre de notices modifiées."""
    return _update_counts(conn, "sp.id BETWEEN :lo AND :hi", {"lo": lo, "hi": hi})


def backfill_source_records(conn: Connection, source_record_ids: list[int]) -> int:
    """Écrit les décomptes des notices `source_record_ids` qui changent. Rend le nombre de notices modifiées."""
    return _update_counts(conn, "sp.id = ANY(:ids)", {"ids": source_record_ids})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    parser.add_argument(
        "--batch", type=int, default=50_000, help="largeur d'un lot, en identifiants"
    )
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        min_id, max_id = conn.execute(text("SELECT min(id), max(id) FROM source_records")).one()
        conn.commit()
        if min_id is None:
            log.info("aucune notice")
            return 0
        changed = 0
        for lo in range(min_id, max_id + 1, args.batch):
            changed += backfill_batch(conn, lo, lo + args.batch - 1)
            if args.dry_run:
                conn.rollback()
            else:
                conn.commit()
        log.info("notices %s : %d", "à modifier" if args.dry_run else "modifiées", changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
