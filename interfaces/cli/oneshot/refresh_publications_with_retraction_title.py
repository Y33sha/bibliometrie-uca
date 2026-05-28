# STATUS: oneshot (2026-05-28)
"""Rejoue `refresh_from_sources` sur les publications candidates à la règle `TITLE_RETRACTION_PREFIX_TO_RETRACTION` (titre commençant par `Retraction notice` / `Retraction note`, `doc_type ∈ {article, other}`).

Sélection : pré-filtre SQL léger qui mirror la liste `_RETRACTION_TITLE_PREFIXES` + `_RETRACTION_APPLIES_TO` côté domain — la cascade `effective_metadata` fait foi côté correction. Volume initial au figeage : 5 publications (1 `article` + 4 `other`) ; les 2 déjà classées `retraction` sont no-op.

Usage :
    python -m interfaces.cli.oneshot.refresh_publications_with_retraction_title [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from application.publications import refresh_from_sources
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import audit_repository, publication_repository

log = setup_logger("refresh_publications_with_retraction_title", os.path.dirname(__file__))

BATCH_COMMIT = 500

# Mirror de `_RETRACTION_TITLE_PREFIXES` côté domain.
_TITLE_PREFIXES = ("retraction notice%", "retraction note%")

# Mirror de `_RETRACTION_APPLIES_TO` côté domain.
_APPLIES_TO = ("article", "other")


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
                    SELECT id
                    FROM publications
                    WHERE title_normalized LIKE ANY(:prefixes)
                      AND doc_type::text = ANY(:applies_to)
                    ORDER BY id
                """),
                {"prefixes": list(_TITLE_PREFIXES), "applies_to": list(_APPLIES_TO)},
            )
            .scalars()
            .all()
        )
        total = len(pub_ids)
        log.info(
            "%d publications candidates à la règle TITLE_RETRACTION_PREFIX_TO_RETRACTION.", total
        )
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
