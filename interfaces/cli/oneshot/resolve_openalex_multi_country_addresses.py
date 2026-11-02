# STATUS: oneshot (2026-11-02)
"""Recompose `addresses.countries` des adresses auxquelles OpenAlex propose plusieurs pays, d'après la préséance du domaine (`retained_countries`).

Les adresses au pays changé entrent dans la file `address_countries_queue`. La phase `countries` du prochain run recalcule ensuite les pays de leurs contributions sources, de leurs enregistrements sources et de leurs publications. Idempotent.

Usage :
    uv run python -m interfaces.cli.oneshot.resolve_openalex_multi_country_addresses [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.transformation.countries.resolution import resolve_address_countries

log = setup_logger("resolve_openalex_multi_country_addresses", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        address_ids = list(
            conn.execute(
                text("""
                    SELECT address_id FROM address_country_candidates
                    WHERE method = 'source_openalex'
                    GROUP BY address_id HAVING count(*) > 1
                    ORDER BY address_id
                """)
            ).scalars()
        )
        log.info("adresses à plusieurs pays proposés par OpenAlex : %d", len(address_ids))
        changed = resolve_address_countries(conn, address_ids)
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
        log.info("adresses au pays %s : %d", "à changer" if args.dry_run else "changé", changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
