# STATUS: oneshot (2026-10-16)
"""Remplit `source_authorships.countries` pour le stock (`refresh_source_contribution_countries`), par lots d'identifiants validés un à un.

Les signatures modifiées sont marquées `countries_dirty` : la phase `countries` suivante recalcule les pays des notices et des publications. Une interruption perd seulement le lot en cours. `--from-id` reprend après le dernier lot validé.

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
    refresh_source_contribution_countries,
)

log = setup_logger("fill_signature_countries", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-id", type=int, help="premier identifiant de signature à traiter")
    parser.add_argument(
        "--batch", type=int, default=2_000_000, help="largeur d'un lot, en identifiants"
    )
    args = parser.parse_args()

    started = time.monotonic()
    changed = 0
    with get_sync_engine().connect() as conn:
        min_id, max_id = conn.execute(text("SELECT min(id), max(id) FROM source_authorships")).one()
        conn.commit()
        lo = args.from_id if args.from_id is not None else min_id
        while lo <= max_id:
            hi = lo + args.batch - 1
            changed += refresh_source_contribution_countries(conn, id_range=(lo, hi))
            conn.commit()
            log.info(
                "signatures %d à %d : %d modifiées au total, %.1f %%, %.0f s",
                lo,
                hi,
                changed,
                100 * (min(hi, max_id) - min_id + 1) / (max_id - min_id + 1),
                time.monotonic() - started,
            )
            lo = hi + 1
    log.info("signatures dont le pays change : %d", changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
