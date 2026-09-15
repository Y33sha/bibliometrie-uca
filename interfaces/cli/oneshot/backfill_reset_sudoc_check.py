# STATUS: oneshot (2026-09-15)
"""Reprend les revues que les passages précédents de la vérification Sudoc ont signalées.

Les règles de la vérification changent au fil des passages : support lu dans `183$a`, ISSN périmés rangés parmi les ISSN rejetés, ISSN d'une autre publication rangés parmi eux au lieu d'être retirés, réunion du papier et de l'en ligne de titres emboîtés, changement de support distingué d'un changement de titre. Le script relève dans le journal du pipeline :

1. les ISSN retirés par un passage précédent, qu'il range parmi les ISSN rejetés de leur revue ;
2. les revues signalées par un message de la vérification, qu'il remet à vérifier.

Le prochain passage de la phase `publishers_journals` vérifie de nouveau ces revues, à partir de leurs ISSN actuels.

Usage :
    python -m interfaces.cli.oneshot.backfill_reset_sudoc_check                     # journal logs/pipeline.log
    python -m interfaces.cli.oneshot.backfill_reset_sudoc_check chemin/du/journal   # autre journal
    python -m interfaces.cli.oneshot.backfill_reset_sudoc_check --dry-run           # rapport seul
"""

from __future__ import annotations

import argparse
import os
import re
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

from infrastructure import PROJECT_ROOT
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.pipeline.journals import PgJournalGatewayQueries

log = setup_logger("backfill_reset_sudoc_check", os.path.dirname(__file__))

# Messages des passages précédents de la vérification Sudoc.
_MESSAGES = (
    "non rangés par support",
    "à égalité",
    "retiré, son ISSN-L",
    "retiré, il désigne",
    "corrigé en",
    "rangé parmi les ISSN rejetés",
    "laissés dans leurs colonnes",
)
_JOURNAL_ID = re.compile(r"Revue (\d+) \(")
_REMOVED_ISSN = re.compile(r"ISSN (\d{4}-\d{3}[\dX]) retiré")


def _read_log(path: Path) -> tuple[list[int], dict[int, list[str]]]:
    """Revues signalées, et ISSN retirés par revue."""
    flagged: set[int] = set()
    removed: dict[int, list[str]] = defaultdict(list)
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            if "publishers_journals" not in line or not any(m in line for m in _MESSAGES):
                continue
            if not (match := _JOURNAL_ID.search(line)):
                continue
            journal_id = int(match.group(1))
            flagged.add(journal_id)
            if issn := _REMOVED_ISSN.search(line):
                removed[journal_id].append(issn.group(1))
    return sorted(flagged), removed


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

    flagged, removed = _read_log(args.log_file)
    log.info("Revues signalées dans %s : %d", args.log_file, len(flagged))
    log.info(
        "ISSN retirés à ranger parmi les rejetés : %d (%d revues)",
        sum(len(v) for v in removed.values()),
        len(removed),
    )

    engine = get_sync_engine()
    with engine.connect() as conn:
        to_reset = conn.execute(
            text(
                "SELECT count(*) FROM journals "
                "WHERE id = ANY(:ids) AND sudoc_checked_at IS NOT NULL"
            ),
            {"ids": flagged},
        ).scalar_one()
        log.info("Revues à remettre à vérifier : %d", to_reset)
        if args.dry_run:
            log.info("DRY-RUN terminé — aucune écriture")
            return 0
        queries = PgJournalGatewayQueries(conn)
        for journal_id, issns in removed.items():
            queries.add_rejected_issns(journal_id, issns)
        conn.execute(
            text("UPDATE journals SET sudoc_checked_at = NULL WHERE id = ANY(:ids)"),
            {"ids": flagged},
        )
        conn.commit()
        log.info("✓ backfill appliqué")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
