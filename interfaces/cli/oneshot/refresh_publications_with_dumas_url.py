# STATUS: oneshot (2026-06-11)
"""Rejoue `refresh_from_sources` sur les publications candidates à la règle `DUMAS_URL_TO_MEMOIR` (au moins une `source_publication` porte une URL `dumas.ccsd`), désormais URL-only.

Rattrapage du stock à l'arrivée de la règle dure : la version précédente, conditionnée à `doc_type = dissertation`, laissait sans correction les publications DUMAS qu'OpenAlex typait autrement (`article`, etc.). Pré-filtre SQL léger ; la décision finale revient à `effective_metadata`.

Usage :
    python -m interfaces.cli.oneshot.refresh_publications_with_dumas_url [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from application.services.publications.core import refresh_from_sources
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import audit_repository, publication_repository

log = setup_logger("refresh_publications_with_dumas_url", os.path.dirname(__file__))

BATCH_COMMIT = 500


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="N'écrit rien : compte les candidates et sort.",
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        pub_ids = (
            conn.execute(
                text("""
                    SELECT p.id
                    FROM publications p
                    WHERE p.doc_type::text <> 'memoir'
                      AND EXISTS (
                          SELECT 1
                          FROM source_publications sp
                          WHERE sp.publication_id = p.id
                            AND EXISTS (
                                SELECT 1 FROM unnest(sp.urls) u WHERE u LIKE '%dumas.ccsd%'
                            )
                      )
                    ORDER BY p.id
                """)
            )
            .scalars()
            .all()
        )
        total = len(pub_ids)
        log.info("%d publications candidates à la règle DUMAS_URL_TO_MEMOIR.", total)
        if total == 0:
            return 0

        if args.dry_run:
            log.info("(dry-run : aucune écriture effective)")
            return 0

        pub_repo = publication_repository(conn)
        audit_repo = audit_repository(conn)
        for i, pub_id in enumerate(pub_ids):
            refresh_from_sources(pub_id, repo=pub_repo, audit_repo=audit_repo)
            if (i + 1) % BATCH_COMMIT == 0:
                conn.commit()
                log.info("  %d/%d rafraîchies…", i + 1, total)
        conn.commit()
        log.info("Terminé : %d publications rafraîchies.", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
