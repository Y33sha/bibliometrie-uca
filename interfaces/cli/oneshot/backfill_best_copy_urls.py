# STATUS: oneshot (2026-10-26)
"""Calcule `best_copy_url` des publications du stock d'après les localisations de leurs enregistrements sources, comme la consolidation d'une publication (`refresh_from_sources`).

Les publications se traitent par lots d'identifiants, un commit par lot. Seules les valeurs qui changent s'écrivent. Idempotent.

Usage :
    python -m interfaces.cli.oneshot.backfill_best_copy_urls [--dry-run] [--batch 5000]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from domain.publications.access import access
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.read_models.publications.copies import publication_copies

log = setup_logger("backfill_best_copy_urls", os.path.dirname(__file__))


def backfill_batch(conn: Connection, lo: int, hi: int) -> int:
    """Écrit `best_copy_url` des publications `[lo, hi]` dont la valeur change. Renvoie le nombre de publications modifiées."""
    rows = conn.execute(
        text("SELECT id, doi, best_copy_url FROM publications WHERE id BETWEEN :lo AND :hi"),
        {"lo": lo, "hi": hi},
    ).all()
    copies = publication_copies(conn, [r.id for r in rows])
    changes = [
        {"id": r.id, "url": url}
        for r in rows
        if (url := access(copies.get(r.id, []), doi=r.doi).url) != r.best_copy_url
    ]
    if changes:
        conn.execute(text("UPDATE publications SET best_copy_url = :url WHERE id = :id"), changes)
    return len(changes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    parser.add_argument(
        "--batch", type=int, default=5_000, help="largeur d'un lot, en identifiants"
    )
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        min_id, max_id = conn.execute(text("SELECT min(id), max(id) FROM publications")).one()
        conn.commit()
        if min_id is None:
            log.info("aucune publication")
            return 0
        changed = 0
        for lo in range(min_id, max_id + 1, args.batch):
            changed += backfill_batch(conn, lo, lo + args.batch - 1)
            if args.dry_run:
                conn.rollback()
            else:
                conn.commit()
        log.info("publications %s : %d", "à modifier" if args.dry_run else "modifiées", changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
