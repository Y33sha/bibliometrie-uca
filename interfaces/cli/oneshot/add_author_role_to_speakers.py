# STATUS: oneshot (2026-10-18)
"""Ajoute le rôle `author` aux signatures du stock qui ont le rôle `speaker` sans lui, comme le fait la normalisation (`map_role`).

Les publications de ces signatures reçoivent `authorships_dirty` : la phase `author_grouping` les regroupe. L'empreinte des signatures reste celle de leur dernière normalisation ; une notice normalisée à nouveau réécrit ses signatures en place.

Usage :
    python -m interfaces.cli.oneshot.add_author_role_to_speakers [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from domain.publications.authorship_roles import AuthorshipRole
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("add_author_role_to_speakers", os.path.dirname(__file__))

_SPEAKERS_WITHOUT_AUTHOR = f"""
    '{AuthorshipRole.SPEAKER.value}' = ANY(sa.roles) AND NOT '{AuthorshipRole.AUTHOR.value}' = ANY(sa.roles)
"""


def add_author_role(conn: Connection) -> tuple[int, int]:
    """Complète les signatures et marque leurs publications. Rend (signatures complétées, publications marquées)."""
    marked = conn.execute(
        text(f"""
            UPDATE publications p SET authorships_dirty = true
            FROM source_authorships sa
            JOIN source_publications sp ON sp.id = sa.source_publication_id
            WHERE p.id = sp.publication_id AND NOT p.authorships_dirty
              AND {_SPEAKERS_WITHOUT_AUTHOR}
        """)  # noqa: S608
    ).rowcount
    updated = conn.execute(
        text(f"""
            UPDATE source_authorships sa
            SET roles = ARRAY['{AuthorshipRole.AUTHOR.value}'] || sa.roles
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
                text(f"SELECT count(*) FROM source_authorships sa WHERE {_SPEAKERS_WITHOUT_AUTHOR}")  # noqa: S608
            ).scalar_one()
            log.info("signatures à compléter : %d", count)
            return 0
        updated, marked = add_author_role(conn)
    log.info("signatures complétées : %d ; publications à regrouper : %d", updated, marked)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
