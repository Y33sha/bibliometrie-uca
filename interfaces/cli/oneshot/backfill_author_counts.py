# STATUS: oneshot (2026-11-06)
"""Calcule `author_count` et `distinct_author_count` des enregistrements sources de brevet d'après leurs contributions sources en base, comme la normalisation (`is_individual_author`). Les inventeurs comptent comme auteurs.

Seules les valeurs qui changent s'écrivent. Idempotent.

Usage :
    uv run python -m interfaces.cli.oneshot.backfill_author_counts [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from domain.documents.doc_types import DocType
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sql_fragments import has_author_role

log = setup_logger("backfill_author_counts", os.path.dirname(__file__))

_AUTHOR = f"NOT sc.collective AND {has_author_role('sc')}"
"""Contribution source d'auteur individuelle, comme `is_individual_author`."""


def _update_counts(conn: Connection, source_records: str, params: dict[str, object]) -> int:
    """Écrit les décomptes modifiés des enregistrements sources retenus par la condition SQL `source_records` (alias `sr`). Renvoie le nombre d'enregistrements sources modifiés."""
    return conn.execute(
        text(f"""
            UPDATE source_records sr
            SET author_count = c.n, distinct_author_count = c.d
            FROM (
                SELECT sr.id,
                       count(sc.id) FILTER (WHERE {_AUTHOR}) AS n,
                       count(DISTINCT (k.last_name_normalized, coalesce(k.first_name_normalized, '')))
                           FILTER (WHERE {_AUTHOR}) AS d
                FROM source_records sr
                LEFT JOIN source_contributions sc ON sc.source_record_id = sr.id
                LEFT JOIN contributor_information k ON k.id = sc.contributor_information_id
                WHERE {source_records}
                GROUP BY sr.id
            ) c
            WHERE sr.id = c.id AND (sr.author_count, sr.distinct_author_count) IS DISTINCT FROM (c.n, c.d)
        """),  # noqa: S608
        params,
    ).rowcount


def backfill_patents(conn: Connection) -> int:
    """Écrit les décomptes modifiés des enregistrements sources de brevet. Renvoie le nombre d'enregistrements sources modifiés."""
    return _update_counts(conn, "sr.doc_type = :doc_type", {"doc_type": DocType.PATENT.value})


def backfill_source_records(conn: Connection, source_record_ids: list[int]) -> int:
    """Écrit les décomptes modifiés des enregistrements sources `source_record_ids`. Renvoie le nombre d'enregistrements sources modifiés."""
    return _update_counts(conn, "sr.id = ANY(:ids)", {"ids": source_record_ids})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        changed = backfill_patents(conn)
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
        log.info(
            "enregistrements sources %s : %d", "à modifier" if args.dry_run else "modifiés", changed
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
