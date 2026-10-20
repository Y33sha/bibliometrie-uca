# STATUS: oneshot (2026-10-19)
"""Répare l'encodage des noms d'auteur du stock (« TÃ©lesphore » → Télesphore, « Fran鏾is » → François), comme le fait la normalisation (`clean_raw_author_name`).

Il retire aussi les accolades LaTeX restées sans commande (« Geß{}ner »). Les contributions sources dont le nom présente un défaut d'encodage (`ENCODING_ERROR_PATTERN`) ou des accolades suivent le traitement de `decode_latex_author_names` : nom réparé, informations du contributeur qui en découlent, personne détachée sauf épinglage, décomptes d'auteurs recalculés, publications à regrouper, lignes de `contributor_information` orphelines supprimées.

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
        rows, source_records = decoded_names(conn, CANDIDATES_SQL, PARAMS)
        log.info(
            "contributions sources à réparer : %d, dans %d enregistrements sources",
            len(rows),
            len(source_records),
        )
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
        orphans = decode(conn, rows, source_records)
        conn.commit()
        log.info(
            "contributions sources réparées : %d ; informations du contributeur orphelines supprimées : %d",
            len(rows),
            orphans,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
