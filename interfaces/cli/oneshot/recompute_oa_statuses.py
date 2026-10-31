# STATUS: oneshot (2026-10-31)
"""Recalcule le statut open access de toutes les publications (`domain.publications.open_access`), d'après leurs copies, leurs embargos, leur type, leur revue et le verdict d'Unpaywall en table.

Les publications se traitent par lots d'identifiants, un commit par lot. Seuls les statuts qui changent s'écrivent. Idempotent. Le bilan donne les passages d'un statut à l'autre.

Usage :
    uv run python -m interfaces.cli.oneshot.recompute_oa_statuses [--dry-run] [--batch 5000]
"""

from __future__ import annotations

import argparse
import os
from collections import Counter

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.transformation.publications.oa_status import OaStatusStore

log = setup_logger("recompute_oa_statuses", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    parser.add_argument(
        "--batch", type=int, default=5_000, help="largeur d'un lot, en identifiants"
    )
    args = parser.parse_args()
    transitions: Counter[tuple[str | None, str]] = Counter()
    with get_sync_engine().connect() as conn:
        min_id, max_id = conn.execute(text("SELECT min(id), max(id) FROM publications")).one()
        conn.commit()
        if min_id is None:
            log.info("aucune publication")
            return 0
        log.info("recalcul du statut open access des publications %d à %d…", min_id, max_id)
        store = OaStatusStore(conn)
        for lo in range(min_id, max_id + 1, args.batch):
            for p in store.fetch_oa_inputs_of(list(range(lo, lo + args.batch))):
                status = p.computed_status()
                if status != p.oa_status:
                    transitions[(p.oa_status, status)] += 1
                    store.update_oa_status(p.id, status)
            if args.dry_run:
                conn.rollback()
            else:
                conn.commit()
        log.info(
            "publications %s : %d",
            "à modifier" if args.dry_run else "modifiées",
            sum(transitions.values()),
        )
        for (before, after), n in transitions.most_common():
            log.info("  %s → %s : %d", before, after, n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
