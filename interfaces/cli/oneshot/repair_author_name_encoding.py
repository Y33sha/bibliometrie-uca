# STATUS: oneshot (2026-10-19)
"""Répare l'encodage des noms d'auteur du stock (« TÃ©lesphore » → Télesphore, « Fran鏾is » → François), comme le fait la normalisation (`clean_raw_author_name`).

Il retire aussi les accolades LaTeX restées sans commande (« Geß{}ner »). Les signatures dont le nom présente un défaut d'encodage (`ENCODING_ERROR_PATTERN`) ou des accolades suivent le traitement de `decode_latex_author_names` : nom réparé, identité qui en découle, personne détachée sauf épinglage, décomptes d'auteurs recalculés, publications à regrouper, identités orphelines supprimées.

Usage :
    python -m interfaces.cli.oneshot.repair_author_name_encoding [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from domain.normalize import ENCODING_ERROR_PATTERN
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from interfaces.cli.oneshot.decode_latex_author_names import candidates_sql, decode, decoded_names

log = setup_logger("repair_author_name_encoding", os.path.dirname(__file__))

CANDIDATES_SQL = candidates_sql("n.names ~ :pattern OR n.names ~ '[{}]'")
PARAMS = {"pattern": ENCODING_ERROR_PATTERN}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        rows, notices = decoded_names(conn, CANDIDATES_SQL, PARAMS)
        log.info("signatures à réparer : %d, dans %d notices", len(rows), len(notices))
        for row in rows[:5]:
            log.info(
                "  %s / %s / %s",
                row["raw_author_name"],
                row["raw_last_name"],
                row["raw_first_name"],
            )
        if args.dry_run or not rows:
            conn.rollback()
            return 0
        orphans = decode(conn, rows, notices)
        conn.commit()
        log.info(
            "signatures réparées : %d ; identités orphelines supprimées : %d", len(rows), orphans
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
