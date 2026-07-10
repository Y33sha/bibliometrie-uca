# STATUS: oneshot (2026-05-28)
"""Rejoue `refresh_from_sources` sur les publications candidates à la règle `TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET` (titre commençant par un préfixe de supplément, `doc_type ∈ {article, other}`).

Sélection : pré-filtre SQL léger qui mirror la liste `_SUPPLEMENTARY_CONTENT_TITLE_PREFIXES` côté domain — la cascade `effective_metadata` fait foi côté correction. Volume initial : 232 publications "additional file" déjà rattrapées au commit précédent, puis ~15 publications supplémentaires (supplementary material/data/etc., data from) au commit qui élargit la règle.

Pas de mécanisme dédié, juste un loop refresh_from_sources : c'est le pattern « rattrapage du stock à l'arrivée d'une règle SP-intrinsèque sans hook admin ».

Usage :
    python -m interfaces.cli.oneshot.refresh_publications_with_supplementary_content_title [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from application.services.publications.core import refresh_from_sources
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import audit_repository, publication_repository

log = setup_logger(
    "refresh_publications_with_supplementary_content_title", os.path.dirname(__file__)
)

BATCH_COMMIT = 500

# Mirror de `_SUPPLEMENTARY_CONTENT_TITLE_PREFIXES` côté domain. Sert au pré-filtre SQL ; la décision finale revient à `effective_metadata`.
_TITLE_PREFIXES = (
    "additional file%",
    "supplementary material%",
    "supplementary data%",
    "supplementary information%",
    "supplementary file%",
    "supplementary dataset%",
    "data from%",
)


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
                      AND doc_type::text IN ('article', 'other')
                    ORDER BY id
                """),
                {"prefixes": list(_TITLE_PREFIXES)},
            )
            .scalars()
            .all()
        )
        total = len(pub_ids)
        log.info(
            "%d publications candidates à la règle TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET.",
            total,
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
