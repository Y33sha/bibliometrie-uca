# STATUS: oneshot (2026-10-17)
"""Marque `source_authorships.collective` sur le stock d'après la règle du nom (`is_collective_name`), par lots d'identifiants validés un à un.

La phase `persons` suivante détache les signatures marquées de leur personne, sauf épinglage, puis supprime les personnes vidées. Une interruption perd seulement le lot en cours. `--from-id` reprend après le dernier lot validé.

Usage :
    python -m interfaces.cli.oneshot.mark_collective_signatures [--dry-run] [--from-id N] [--batch 1000000]
"""

from __future__ import annotations

import argparse
import os
import time

from sqlalchemy import Connection, text

from domain.persons.collective_names import is_collective_name
from domain.persons.signature_name import SignatureName
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("mark_collective_signatures", os.path.dirname(__file__))


def _collective_ids(conn: Connection, lo: int, hi: int) -> list[int]:
    """Signatures non marquées du lot `[lo, hi]` dont le nom désigne un collectif."""
    rows = conn.execute(
        text("""
            SELECT id, raw_author_name, raw_last_name, raw_first_name
            FROM source_authorships
            WHERE id BETWEEN :lo AND :hi AND NOT collective
        """),
        {"lo": lo, "hi": hi},
    )
    return [
        r.id
        for r in rows
        if is_collective_name(
            SignatureName.from_columns(
                r.raw_author_name, r.raw_last_name, r.raw_first_name
            ).display()
        )
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    parser.add_argument("--from-id", type=int, help="premier identifiant de signature à traiter")
    parser.add_argument(
        "--batch", type=int, default=1_000_000, help="largeur d'un lot, en identifiants"
    )
    args = parser.parse_args()

    started = time.monotonic()
    marked = 0
    with get_sync_engine().connect() as conn:
        min_id, max_id = conn.execute(text("SELECT min(id), max(id) FROM source_authorships")).one()
        conn.commit()
        lo = args.from_id if args.from_id is not None else min_id
        while lo <= max_id:
            hi = lo + args.batch - 1
            ids = _collective_ids(conn, lo, hi)
            if ids and not args.dry_run:
                conn.execute(
                    text("UPDATE source_authorships SET collective = true WHERE id = ANY(:ids)"),
                    {"ids": ids},
                )
            conn.commit()
            marked += len(ids)
            log.info(
                "signatures %d à %d : %d collectives au total, %.1f %%, %.0f s",
                lo,
                hi,
                marked,
                100 * (min(hi, max_id) - min_id + 1) / (max_id - min_id + 1),
                time.monotonic() - started,
            )
            lo = hi + 1
    log.info("signatures collectives %s : %d", "trouvées" if args.dry_run else "marquées", marked)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
