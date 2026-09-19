# STATUS: oneshot (2026-09-19)
"""Défait les rattachements de revue par préfixe DOI.

La sous-étape `journal_by_doi` de `metadata_correction` rattachait à une revue l'enregistrement sans revue dont le DOI commençait par le `doi_prefix` de cette revue. Elle n'apportait de revue à aucune publication, et en imposait de fausses : blocs d'ISBN (`10.1007/978-3-030` pour *Lecture Notes in Mathematics*), préfixes qui coupent un mot (`10.1016/j.ins`). Ce script remet à NULL le `journal_id` de ces enregistrements, retire la trace de `raw_metadata` et les marque `keys_dirty` : la phase `publications` recalcule ensuite la revue de leurs publications.

Usage :
    python -m interfaces.cli.oneshot.backfill_drop_journal_by_doi_prefix             # applique
    python -m interfaces.cli.oneshot.backfill_drop_journal_by_doi_prefix --dry-run   # rapport seul
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_drop_journal_by_doi_prefix", os.path.dirname(__file__))

_DETACH = text("""
    UPDATE source_publications
    SET journal_id = NULL,
        raw_metadata = raw_metadata - 'journal_id',
        keys_dirty = TRUE,
        updated_at = clock_timestamp()
    WHERE raw_metadata->'journal_id'->>'corrected_by' = 'JOURNAL_BY_DOI_PREFIX'
""")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        detached = conn.execute(_DETACH).rowcount
        log.info("%d enregistrements détachés de leur revue", detached)
        if args.dry_run:
            conn.rollback()
            log.info("DRY-RUN terminé — aucune écriture")
            return 0
        conn.commit()
        log.info("✓ backfill appliqué")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
