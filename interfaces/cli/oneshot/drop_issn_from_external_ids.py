# STATUS: oneshot (2026-09-22)
"""Retire la clé `issn` des `external_ids` des enregistrements.

L'ISSN identifie la revue, pas le document : chaque source le range dans `biblio.journal`. Seule la normalisation Crossref le recopiait aussi dans `external_ids`.

Usage :
    python -m interfaces.cli.oneshot.drop_issn_from_external_ids [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("drop_issn_from_external_ids", os.path.dirname(__file__))

_COUNT = text("SELECT count(*) FROM source_publications WHERE external_ids ? 'issn'")
_DROP = text(
    "UPDATE source_publications SET external_ids = external_ids - 'issn' WHERE external_ids ? 'issn'"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte sans rien modifier.")
    args = parser.parse_args()
    with get_sync_engine().begin() as conn:
        if args.dry_run:
            log.info(
                "Enregistrements avec un ISSN dans external_ids : %d",
                conn.execute(_COUNT).scalar_one(),
            )
            return 0
        log.info("ISSN retiré de %d enregistrements", conn.execute(_DROP).rowcount)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
