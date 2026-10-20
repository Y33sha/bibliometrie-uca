# STATUS: oneshot (2026-10-18)
"""Marque `source_contributions.collective` sur le stock d'après la règle du nom (`is_collective_name`), par lots d'identifiants validés un à un.

Les décomptes d'auteurs des notices touchées sont recalculés et leurs publications sont à regrouper. La phase `persons` suivante détache les signatures marquées de leur personne, sauf épinglage, puis supprime les personnes vidées. Une interruption perd seulement le lot en cours. `--from-id` reprend après le dernier lot validé. `--contains` restreint l'examen aux noms bruts qui contiennent un texte.

Usage :
    python -m interfaces.cli.oneshot.mark_collective_signatures [--dry-run] [--contains "et al"] [--from-id N] [--batch 1000000]
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
from interfaces.cli.oneshot.backfill_author_counts import backfill_notices

log = setup_logger("mark_collective_signatures", os.path.dirname(__file__))


def _collective_ids(conn: Connection, lo: int, hi: int, contains: str | None = None) -> list[int]:
    """Signatures non marquées du lot `[lo, hi]` dont le nom désigne un collectif. `contains` restreint le lot aux noms bruts qui contiennent ce texte, sans tenir compte de la casse."""
    rows = conn.execute(
        text("""
            SELECT id, raw_author_name, raw_last_name, raw_first_name
            FROM source_contributions
            WHERE id BETWEEN :lo AND :hi AND NOT collective
              AND (CAST(:pattern AS text) IS NULL
                   OR concat_ws(' ', raw_author_name, raw_first_name, raw_last_name) ILIKE :pattern)
        """),
        {"lo": lo, "hi": hi, "pattern": f"%{contains}%" if contains else None},
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


def mark_collective(conn: Connection, ids: list[int]) -> None:
    """Marque collectives les signatures `ids`, recalcule les décomptes d'auteurs de leurs notices et met leurs publications à regrouper."""
    notice_ids = list(
        conn.execute(
            text("""
                UPDATE source_contributions SET collective = true WHERE id = ANY(:ids)
                RETURNING source_record_id
            """),
            {"ids": ids},
        ).scalars()
    )
    backfill_notices(conn, sorted(set(notice_ids)))
    conn.execute(
        text("""
            UPDATE publications p SET contributions_dirty = true
            FROM source_records sp
            WHERE sp.id = ANY(:notices) AND p.id = sp.publication_id AND NOT p.contributions_dirty
        """),
        {"notices": notice_ids},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    parser.add_argument("--from-id", type=int, help="premier identifiant de signature à traiter")
    parser.add_argument("--contains", help="texte que le nom brut doit contenir")
    parser.add_argument(
        "--batch", type=int, default=1_000_000, help="largeur d'un lot, en identifiants"
    )
    args = parser.parse_args()

    started = time.monotonic()
    marked = 0
    with get_sync_engine().connect() as conn:
        min_id, max_id = conn.execute(
            text("SELECT min(id), max(id) FROM source_contributions")
        ).one()
        conn.commit()
        lo = args.from_id if args.from_id is not None else min_id
        while lo <= max_id:
            hi = lo + args.batch - 1
            ids = _collective_ids(conn, lo, hi, args.contains)
            if ids and not args.dry_run:
                mark_collective(conn, ids)
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
