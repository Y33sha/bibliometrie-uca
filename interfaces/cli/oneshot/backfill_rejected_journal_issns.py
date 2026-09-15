# STATUS: oneshot (2026-09-15)
"""Réinjecte dans `journals.rejected_issns` les ISSN invalides supprimés par `backfill_normalize_journal_issns`.

Ce backfill remplaçait par NULL les ISSN invalides des revues, avant que `rejected_issns` existe. La liste reprend son journal d'exécution. Idempotent.

Usage :
    python -m interfaces.cli.oneshot.backfill_rejected_journal_issns            # exécution
    python -m interfaces.cli.oneshot.backfill_rejected_journal_issns --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.pipeline.journals import PgJournalGatewayQueries

log = setup_logger("backfill_rejected_journal_issns", os.path.dirname(__file__))

# (revue, valeur écartée), tels que journalisés par `backfill_normalize_journal_issns`.
_REJECTED = (
    (120, "1467-2494"),
    (248, "1365-8711"),
    (285, "1745-1707"),
    (801, "1790-6295"),
    (7712, "1016-7365"),
    (7977, "6854-1423"),
    (11637, "0033-4533"),
    (18730, "1365-4362"),
    (20371, "1963-6301"),
    (20389, "1950-629"),
    (20643, "1174-4547"),
    (20727, "2352-6585"),
    (20761, "1928-5724"),
    (20819, "2034-8504"),
    (67096, "1855-6201"),
    (83640, "1950-2051"),
    (83954, "1750-2676"),
    (96025, "1234-987X"),
    (96121, "1471-5004"),
    (96324, "9781450348850"),
    (96965, "1298-0124"),
    (100950, "2710-130x"),
    (101611, "1789-1504"),
    (101846, "(Internet)"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()
    apply = not args.dry_run

    values_by_journal: dict[int, list[str]] = defaultdict(list)
    for journal_id, value in _REJECTED:
        values_by_journal[journal_id].append(value)

    engine = get_sync_engine()
    with engine.connect() as conn:
        queries = PgJournalGatewayQueries(conn)
        for journal_id, values in values_by_journal.items():
            log.info("revue %d : %s", journal_id, values)
            if apply:
                queries.add_rejected_issns(journal_id, values)
        if apply:
            conn.commit()
            log.info("✓ %d revues mises à jour", len(values_by_journal))
        else:
            log.info("DRY-RUN terminé — aucune écriture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
