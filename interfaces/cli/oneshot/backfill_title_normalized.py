# STATUS: oneshot (2026-06-15)
"""Backfill de `source_publications.title_normalized` sur le stock existant.

Les upserts du `normalize` remplissent désormais `title_normalized` au même mouvement que
`title`, mais les SP déjà en base ont la colonne `NULL`. Ce one-shot la calcule
(`domain.publications.metadata.normalized_title`) pour toutes les SP `title_normalized IS NULL`.
`title` étant INSERT-only, le backfill est définitif (pas de recompute à entretenir).

Peupler `title_normalized` **arme le token métadonnée** (`metadata_block` = `(doc_type, titre,
année)`) : c'est une mutation de clé. Le one-shot pose donc `keys_dirty = true` sur **toute** SP
qui gagne ce token (doc_type présent, titre assez long, année présente — cf. `keys.py`), pour que
la réconciliation matérialise les fusions au prochain run de la phase `publications`. Les SP sans
titre assez long ne gagnent rien (leur dédup par identifiant est indépendante de ce backfill).

Usage :
    python -m interfaces.cli.oneshot.backfill_title_normalized [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from domain.publications.metadata import normalized_title
from domain.source_publications.keys import DISCRIMINANT_TITLE_MIN_LENGTH
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_title_normalized", os.path.dirname(__file__))

BATCH = 5000

# SP qui gagnent le token `metadata_block` quand `title_normalized` se remplit (cf. `keys.py`) :
# tout doc_type, titre plus long que le seuil discriminant, année présente.
_GAINS_TOKEN = (
    "doc_type IS NOT NULL "
    f"AND length(title_normalized) > {DISCRIMINANT_TITLE_MIN_LENGTH} "
    "AND pub_year IS NOT NULL"
)


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
            # Estimation avant backfill : `title_normalized` est NULL, on approxime la longueur
            # sur le titre brut (≈ la forme normalisée) pour compter les futurs marquages.
            to_dirty = conn.execute(
                text(
                    "SELECT count(*) FROM source_publications "
                    "WHERE doc_type IS NOT NULL AND pub_year IS NOT NULL "
                    f"AND length(COALESCE(title_normalized, title, '')) > {DISCRIMINANT_TITLE_MIN_LENGTH}"
                )
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

        # `title_normalized` peuplé ⇒ token `metadata_block` armé : re-dirtier toute SP qui le
        # gagne, pour que la réconciliation matérialise les fusions au prochain run `publications`.
        # `_GAINS_TOKEN` est un fragment de condition constant (pas une valeur) — interpolation sûre.
        marked = conn.execute(
            text(f"UPDATE source_publications SET keys_dirty = true WHERE {_GAINS_TOKEN}")  # noqa: S608
        ).rowcount
        conn.commit()
        log.info(
            "✓ %d source_publications marquées keys_dirty (gagnent le token metadata_block)", marked
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
