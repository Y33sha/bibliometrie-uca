# STATUS: maintenance
"""Re-marque `keys_dirty` sur les source_publications pour forcer une re-réconciliation.

Quand une règle de clés de confirmation évolue (nouveau token, seuil de garde, projection revue
dans `domain/source_publications/keys.py`), le stock déjà réconcilié ne reflète plus la règle :
les fusions/scissions qu'elle implique ne sont pas matérialisées. Ce script re-marque `keys_dirty`
sur les SP concernées ; la phase `publications` (réconciliation) les retraite au prochain run —
sur tout le stock, c'est le *cluster-then-materialize* complet.

Sans `--where`, marque **tout le stock** (rebuild complet). `--where` cible un sous-ensemble
(fragment SQL de confiance, ex. la condition d'une règle précise) :

    python -m interfaces.cli.maintenance.redirty_publications
    python -m interfaces.cli.maintenance.redirty_publications --where "doc_type = 'book_chapter'"
    python -m interfaces.cli.maintenance.redirty_publications --dry-run

Puis matérialiser : `python run_pipeline.py --only publications` (ou directement
`run_pipeline.py --only publications --rebuild-publications`, qui enchaîne le re-dirty total et la
réconciliation).
"""

from __future__ import annotations

import argparse
import os

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.publications.reconciliation import mark_keys_dirty

log = setup_logger("redirty_publications", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--where",
        metavar="SQL",
        help="Condition SQL ciblant un sous-ensemble (défaut : tout le stock).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compte les SP visées sans écrire.")
    args = parser.parse_args()

    cible = f" (where: {args.where})" if args.where else " (tout le stock)"
    engine = get_sync_engine()
    with engine.connect() as conn:
        if args.dry_run:
            n = mark_keys_dirty(conn, args.where, dry_run=True)
            log.info("DRY-RUN : %d source_publications seraient marquées keys_dirty%s", n, cible)
            return 0
        n = mark_keys_dirty(conn, args.where)
        conn.commit()
        log.info("✓ %d source_publications marquées keys_dirty%s", n, cible)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
