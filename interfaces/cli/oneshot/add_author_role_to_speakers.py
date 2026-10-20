# STATUS: oneshot (2026-10-18)
"""Ajoute le rôle `author` aux contributions sources du stock qui ont le rôle `speaker` sans lui, comme le fait la normalisation (`map_role`).

Les publications de ces contributions sources reçoivent `contributions_dirty` : la phase `author_grouping` les regroupe. L'empreinte des contributions sources reste celle de leur dernière normalisation ; un enregistrement source normalisé à nouveau réécrit ses contributions sources en place.

Usage :
    python -m interfaces.cli.oneshot.add_author_role_to_speakers [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from domain.publications.contribution_roles import ContributionRole
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("add_author_role_to_speakers", os.path.dirname(__file__))

_SPEAKERS_WITHOUT_AUTHOR = f"""
    '{ContributionRole.SPEAKER.value}' = ANY(sc.roles) AND NOT '{ContributionRole.AUTHOR.value}' = ANY(sc.roles)
"""


def add_author_role(conn: Connection) -> tuple[int, int]:
    """Complète les contributions sources et marque leurs publications. Rend (contributions sources complétées, publications marquées)."""
    marked = conn.execute(
        text(f"""
            UPDATE publications p SET contributions_dirty = true
            FROM source_contributions sc
            JOIN source_records sr ON sr.id = sc.source_record_id
            WHERE p.id = sr.publication_id AND NOT p.contributions_dirty
              AND {_SPEAKERS_WITHOUT_AUTHOR}
        """)  # noqa: S608
    ).rowcount
    updated = conn.execute(
        text(f"""
            UPDATE source_contributions sc
            SET roles = ARRAY['{ContributionRole.AUTHOR.value}'] || sc.roles
            WHERE {_SPEAKERS_WITHOUT_AUTHOR}
        """)  # noqa: S608
    ).rowcount
    return updated, marked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()

    with get_sync_engine().begin() as conn:
        if args.dry_run:
            count = conn.execute(
                text(
                    f"SELECT count(*) FROM source_contributions sc WHERE {_SPEAKERS_WITHOUT_AUTHOR}"
                )  # noqa: S608
            ).scalar_one()
            log.info("contributions sources à compléter : %d", count)
            return 0
        updated, marked = add_author_role(conn)
    log.info(
        "contributions sources complétées : %d ; publications à regrouper : %d", updated, marked
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
