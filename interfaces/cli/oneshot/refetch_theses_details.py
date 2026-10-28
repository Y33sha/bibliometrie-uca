# STATUS: oneshot (2026-10-28)
"""Relit le détail de toutes les thèses de `staging` (API de détail de theses.fr), par la relecture de la tâche `fetch_stale.theses`.

Le détail de chaque thèse s'écrit dans `staging`. Les thèses dont le contenu change repassent à la normalisation. Une requête à la fois.

Usage :
    python -m interfaces.cli.oneshot.refetch_theses_details [--dry-run]

Puis : `run_pipeline --from normalize --sources theses`.
"""

from __future__ import annotations

import argparse
import asyncio
import os

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.ingestion.common.stale_refetch import get_stale_source_ids, refresh
from pipeline.ingestion.theses.fetch_stale import ThesesStaleRefetch

log = setup_logger("refetch_theses_details", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte les thèses sans les relire")
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        if args.dry_run:
            log.info("%d thèses à relire", len(get_stale_source_ids(conn, "theses", after_days=0)))
            return 0
        metrics = asyncio.run(refresh(conn, ThesesStaleRefetch(), log, after_days=0))
        conn.commit()
    log.info(
        "%d thèses relues : %d mises à jour, %d inchangées, %d disparues, %d en erreur",
        metrics.total,
        metrics.updated,
        metrics.unchanged,
        metrics.extras.get("disappeared", 0),
        metrics.errors,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
