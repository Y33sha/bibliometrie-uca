# STATUS: oneshot (2026-09-17)
"""Marque `keys_dirty` les enregistrements sans publication qui ont une signature dans le périmètre.

La phase `affiliations` marque ces enregistrements quand une signature entre dans le périmètre. Les enregistrements entrés dans le périmètre avant cette règle sont restés sans publication. La prochaine phase `publications` les met en publication, sauf ceux dont le type est hors périmètre (mémoires, évaluations par les pairs).

Usage :
    python -m interfaces.cli.oneshot.backfill_mark_orphans_in_perimeter_dirty             # applique
    python -m interfaces.cli.oneshot.backfill_mark_orphans_in_perimeter_dirty --dry-run   # rapport seul
"""

from __future__ import annotations

import argparse
import os

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.pipeline.publications.reconciliation import mark_keys_dirty

log = setup_logger("backfill_mark_orphans_in_perimeter_dirty", os.path.dirname(__file__))

_ORPHANS_IN_PERIMETER = (
    "publication_id IS NULL AND NOT keys_dirty AND EXISTS ("
    "SELECT 1 FROM source_authorships sa"
    " WHERE sa.source_publication_id = source_publications.id AND sa.in_perimeter)"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        n = mark_keys_dirty(conn, _ORPHANS_IN_PERIMETER, dry_run=args.dry_run)
        if args.dry_run:
            log.info("Enregistrements à marquer : %d", n)
            log.info("DRY-RUN terminé — aucune écriture")
            return 0
        conn.commit()
        log.info("✓ %d enregistrements marqués keys_dirty", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
