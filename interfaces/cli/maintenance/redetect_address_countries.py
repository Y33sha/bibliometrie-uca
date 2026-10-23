# STATUS: maintenance
"""Marque toutes les adresses pour une nouvelle détection de leur pays, après une modification de `place_name_forms`.

Le run suivant de la phase `countries` recalcule les candidats `country_name`, `institution` et `city` de tout le stock, puis résout chaque adresse.

Usage :
    python -m interfaces.cli.maintenance.redetect_address_countries [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.transformation.countries.store import CountryCandidatesStore

log = setup_logger("redetect_address_countries", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="compte les adresses sans les marquer"
    )
    args = parser.parse_args()

    with get_sync_engine().begin() as conn:
        if args.dry_run:
            count = conn.execute(text("SELECT count(*) FROM addresses")).scalar_one()
            log.info("adresses à marquer : %d", count)
            return 0
        marked = CountryCandidatesStore(conn).mark_all_for_detection()
    log.info("adresses marquées : %d ; lancer run_pipeline --only countries", marked)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
