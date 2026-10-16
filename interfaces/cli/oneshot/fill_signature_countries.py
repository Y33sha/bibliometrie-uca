# STATUS: oneshot (2026-10-16)
"""Remplit `source_authorships.countries` pour le stock, en une passe (`CountryQueries.refresh_signature_countries`, portée complète).

Les signatures modifiées sont marquées `countries_dirty` : la phase `countries` suivante en recalcule les pays des notices et des publications.

Usage :
    python -m interfaces.cli.oneshot.fill_signature_countries
"""

from __future__ import annotations

import os

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.transformation.structures.countries.countries_queries import CountryQueries

log = setup_logger("fill_signature_countries", os.path.dirname(__file__))


def main() -> int:
    with get_sync_engine().begin() as conn:
        changed = CountryQueries().refresh_signature_countries(conn, full=True)
    log.info("signatures dont le pays change : %d", changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
