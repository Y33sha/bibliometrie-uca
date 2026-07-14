"""Rejoue `refresh_from_sources` sur toutes les publications rattachées à un journal d'un `journal_type` donné, dont le `doc_type` canonique diverge d'`effective_metadata` (= la règle de correction associée n'a pas encore été appliquée).

Cas d'usage : après l'ajout d'une règle journal-dépendante dans `effective_metadata` (ex. `JOURNAL_TYPE_MEDIA_TO_MEDIA`), rattraper les journaux déjà typés à la main avant l'existence de la règle — leurs publications n'ont pas été passées par le hook admin de requalification.

Usage :
    python -m interfaces.cli.maintenance.refresh_publications_for_journal_type --journal-type media [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from application.services.publications.core import refresh_from_sources
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import publication_repository

log = setup_logger("refresh_publications_for_journal_type", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--journal-type", required=True, help="Type de journal cible (ex. 'media')."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="N'écrit rien : liste les publications cibles et sort.",
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        pub_ids = (
            conn.execute(
                text("""
                    SELECT p.id
                    FROM publications p
                    JOIN journals j ON j.id = p.journal_id
                    WHERE j.journal_type::text = :jt
                      AND p.doc_type::text != :jt
                    ORDER BY p.id
                """),
                {"jt": args.journal_type},
            )
            .scalars()
            .all()
        )
        total = len(pub_ids)
        log.info(
            "%d publications dans des journaux de type '%s' avec doc_type divergent.",
            total,
            args.journal_type,
        )
        if total == 0:
            return 0

        if args.dry_run:
            log.info("(dry-run : aucune écriture effective)")
            log.info("Ids : %s", list(pub_ids))
            return 0

        pub_repo = publication_repository(conn)
        for pub_id in pub_ids:
            refresh_from_sources(pub_id, repo=pub_repo)
        conn.commit()
        log.info("Terminé : %d publications rafraîchies.", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
