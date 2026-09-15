# STATUS: oneshot (2026-09-15)
"""Remet à vérifier dans le Sudoc les revues que le premier passage a signalées.

Les règles de la vérification changent : support lu dans `183$a`, ISSN périmés rangés parmi les ISSN rejetés, liens d'autre support (`452`). Les revues concernées sont celles que le premier passage a laissées en l'état ou modifiées avec un message : ISSN non rangés, ISSN-L à égalité, ISSN retiré, ISSN corrigé. Le script les relève dans le journal du pipeline. Le prochain passage de la phase `publishers_journals` les vérifie de nouveau, à partir de leurs ISSN actuels.

Usage :
    python -m interfaces.cli.oneshot.backfill_reset_sudoc_check                     # journal logs/pipeline.log
    python -m interfaces.cli.oneshot.backfill_reset_sudoc_check chemin/du/journal   # autre journal
    python -m interfaces.cli.oneshot.backfill_reset_sudoc_check --dry-run           # rapport seul
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from sqlalchemy import text

from infrastructure import PROJECT_ROOT
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_reset_sudoc_check", os.path.dirname(__file__))

# Messages du premier passage de la vérification Sudoc.
_MESSAGES = ("non rangés par support", "à égalité", "retiré, son ISSN-L", "corrigé en")
_JOURNAL_ID = re.compile(r"Revue (\d+) \(")


def _flagged_journal_ids(path: Path) -> list[int]:
    ids: set[int] = set()
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            if "publishers_journals" not in line or not any(m in line for m in _MESSAGES):
                continue
            if match := _JOURNAL_ID.search(line):
                ids.add(int(match.group(1)))
    return sorted(ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "log_file",
        nargs="?",
        type=Path,
        default=PROJECT_ROOT / "logs" / "pipeline.log",
        help="Journal du pipeline (défaut : logs/pipeline.log).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()

    ids = _flagged_journal_ids(args.log_file)
    log.info("Revues signalées dans %s : %d", args.log_file, len(ids))

    engine = get_sync_engine()
    with engine.connect() as conn:
        to_reset = conn.execute(
            text(
                "SELECT count(*) FROM journals "
                "WHERE id = ANY(:ids) AND sudoc_checked_at IS NOT NULL"
            ),
            {"ids": ids},
        ).scalar_one()
        log.info("Revues à remettre à vérifier : %d", to_reset)
        if args.dry_run:
            log.info("DRY-RUN terminé — aucune écriture")
            return 0
        conn.execute(
            text("UPDATE journals SET sudoc_checked_at = NULL WHERE id = ANY(:ids)"),
            {"ids": ids},
        )
        conn.commit()
        log.info("✓ backfill appliqué")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
