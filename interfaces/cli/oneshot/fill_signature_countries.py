# STATUS: oneshot (2026-10-16)
"""Remplit `source_contributions.countries` pour le stock (`refresh_source_contribution_countries_in_id_range`), par lots d'identifiants validés un à un.

Les contributions sources modifiées sont marquées `countries_dirty` : la phase `countries` suivante recalcule les pays des enregistrements sources et des publications. Une interruption perd seulement le lot en cours. `--from-id` reprend après le dernier lot validé.

Usage :
    python -m interfaces.cli.oneshot.fill_signature_countries [--from-id N] [--batch 2000000]
"""

from __future__ import annotations

import argparse
import os
import time

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.transformation.countries.refresh_publication_countries import (
    refresh_source_contribution_countries_in_id_range,
)

log = setup_logger("fill_signature_countries", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-id", type=int, help="premier identifiant de contribution source à traiter"
    )
    parser.add_argument(
        "--batch", type=int, default=2_000_000, help="largeur d'un lot, en identifiants"
    )
    args = parser.parse_args()

    started = time.monotonic()
    changed = 0
    with get_sync_engine().connect() as conn:
        min_id, max_id = conn.execute(
            text("SELECT min(id), max(id) FROM source_contributions")
        ).one()
        conn.commit()
        lo = args.from_id if args.from_id is not None else min_id
        while lo <= max_id:
            hi = lo + args.batch - 1
            changed += refresh_source_contribution_countries_in_id_range(conn, (lo, hi))
            conn.commit()
            log.info(
                "contributions sources %d à %d : %d modifiées au total, %.1f %%, %.0f s",
                lo,
                hi,
                changed,
                100 * (min(hi, max_id) - min_id + 1) / (max_id - min_id + 1),
                time.monotonic() - started,
            )
            lo = hi + 1
    log.info("contributions sources dont le pays change : %d", changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
