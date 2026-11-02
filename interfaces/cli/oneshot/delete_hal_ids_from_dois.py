# STATUS: oneshot (2026-11-01)
"""Supprime les identifiants HAL des enregistrements sources OpenAlex contenus dans un de leurs DOI, et marque ces enregistrements sources pour la réconciliation.

Un identifiant de localisation OpenAlex `doi:<doi>` contient parfois un fragment au format d'un identifiant HAL : `doi:10.3929/ethz-b-000124558` contient `b-000124558`. `HALId.normalize` reconnaît un identifiant HAL nu seulement s'il forme toute la chaîne. Le script aligne le stock sur cette règle.

Usage :
    uv run python -m interfaces.cli.oneshot.delete_hal_ids_from_dois [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from domain.source_records.identifiers import SourceIdentifierType
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger

log = setup_logger("delete_hal_ids_from_dois", os.path.dirname(__file__))

_TARGETS_SQL = text(f"""
    SELECT i.source_record_id, i.id_value
    FROM source_record_identifiers i
    JOIN source_records sr ON sr.id = i.source_record_id
    WHERE i.id_type = '{SourceIdentifierType.HAL_ID.value}'
      AND sr.source = 'openalex'
      AND EXISTS (
          SELECT 1 FROM source_record_identifiers d
          WHERE d.source_record_id = i.source_record_id
            AND d.id_type = '{SourceIdentifierType.DOI.value}'
            AND strpos(d.id_value, i.id_value) > 0
      )
""")

_DELETE_SQL = text(f"""
    DELETE FROM source_record_identifiers i
    USING unnest(CAST(:records AS integer[]), CAST(:values AS text[])) AS t(source_record_id, id_value)
    WHERE i.source_record_id = t.source_record_id
      AND i.id_type = '{SourceIdentifierType.HAL_ID.value}'
      AND i.id_value = t.id_value
""")


def find_targets(conn: Connection) -> list[tuple[int, str]]:
    """Renvoie les identifiants HAL visés : `(enregistrement source, valeur)`."""
    return [(r.source_record_id, r.id_value) for r in conn.execute(_TARGETS_SQL)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        targets = find_targets(conn)
    records = sorted({record for record, _ in targets})
    log.info(
        "Identifiants HAL visés : %d, sur %d enregistrements sources", len(targets), len(records)
    )
    for record, value in targets[:10]:
        log.info("  enregistrement source %d : %s", record, value)
    if not targets or args.dry_run:
        return 0

    with engine.begin() as conn:
        deleted = conn.execute(
            _DELETE_SQL,
            {"records": [r for r, _ in targets], "values": [v for _, v in targets]},
        ).rowcount
        marked = enqueue(
            conn,
            Queue.SOURCE_RECORD_KEYS,
            "SELECT unnest(CAST(:ids AS integer[]))",
            {"ids": records},
        )
    log.info(
        "Supprimés : %d identifiants HAL ; %d enregistrements sources marqués", deleted, marked
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
