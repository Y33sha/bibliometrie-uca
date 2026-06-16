# STATUS: oneshot (2026-06-15)
"""Backfill de `source_publications.title_normalized` sur le stock existant.

Les upserts du `normalize` remplissent désormais `title_normalized` au même mouvement que
`title`, mais les SP déjà en base ont la colonne `NULL`. Ce one-shot la calcule
(`domain.publications.metadata.normalized_title`) pour toutes les SP `title_normalized IS NULL`.
`title` étant INSERT-only, le backfill est définitif (pas de recompute à entretenir).

Peupler `title_normalized` **arme les tokens métadonnée** (`thesis_meta`, `metadata_block`) :
c'est une mutation de clé. Le one-shot pose donc `keys_dirty = true` sur les doc_types qui
gagnent un token (cf. `_TOKEN_DOC_TYPES`), pour que la réconciliation les ré-évalue au prochain
run de la phase `publications`. Les autres types ne gagnent aucun token par `title_normalized`
(et leur dédup par identifiant est indépendante de ce backfill).

Usage :
    python -m interfaces.cli.oneshot.backfill_title_normalized [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from domain.publications.metadata import normalized_title
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_title_normalized", os.path.dirname(__file__))

BATCH = 5000

# doc_types dont le jeu de tokens change quand `title_normalized` se remplit (token thèse +
# token bloc tier-1) — cf. `_THESIS_DOC_TYPES` / `_TIER1_DOC_TYPES` dans
# `domain/source_publications/keys.py`. À garder synchrone.
_TOKEN_DOC_TYPES = ("thesis", "ongoing_thesis", "conference_paper", "poster", "book_chapter")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Compte les SP à backfiller et sort."
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        if args.dry_run:
            n = conn.execute(
                text("SELECT count(*) FROM source_publications WHERE title_normalized IS NULL")
            ).scalar_one()
            to_dirty = conn.execute(
                text(
                    "SELECT count(*) FROM source_publications "
                    "WHERE doc_type = ANY(:types) AND title_normalized IS NULL"
                ),
                {"types": list(_TOKEN_DOC_TYPES)},
            ).scalar_one()
            log.info(
                "DRY-RUN : %d source_publications à backfiller, dont %d à marquer keys_dirty",
                n,
                to_dirty,
            )
            return 0

        total = 0
        while True:
            rows = conn.execute(
                text(
                    "SELECT id, title FROM source_publications "
                    "WHERE title_normalized IS NULL LIMIT :lim"
                ),
                {"lim": BATCH},
            ).all()
            if not rows:
                break
            conn.execute(
                text("UPDATE source_publications SET title_normalized = :tn WHERE id = :id"),
                [{"id": r.id, "tn": normalized_title(r.title)} for r in rows],
            )
            conn.commit()
            total += len(rows)
            log.info("  %d backfillés...", total)
        log.info("✓ %d title_normalized backfillés", total)

        # `title_normalized` peuplé ⇒ tokens métadonnée armés : re-dirtier les types concernés
        # pour que la réconciliation matérialise les fusions au prochain run `publications`.
        marked = conn.execute(
            text(
                "UPDATE source_publications SET keys_dirty = true "
                "WHERE doc_type = ANY(:types) AND title_normalized IS NOT NULL"
            ),
            {"types": list(_TOKEN_DOC_TYPES)},
        ).rowcount
        conn.commit()
        log.info("✓ %d source_publications marquées keys_dirty (types à token métadonnée)", marked)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
