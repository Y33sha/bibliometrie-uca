# STATUS: oneshot (2026-10-25)
"""Rattache les enregistrements sources du stock à l'éditeur nommé par leur source, comme la normalisation.

Le nom d'éditeur se lit dans `biblio.publisher`. L'éditeur est trouvé ou créé par ses formes de nom (`find_or_create_publisher`). Une production hébergée sans être publiée reste sans éditeur (`source_record_has_publisher`). Les enregistrements sources dont l'éditeur change passent dans la file de réconciliation : la phase `publications` recalcule ensuite l'éditeur de leurs publications. Idempotent.

Usage :
    uv run python -m interfaces.cli.oneshot.backfill_source_record_publishers [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import Connection, text

from domain.publishers.attribution import source_record_has_publisher
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger
from pipeline.transformation.publishing.find_or_create import find_or_create_publisher
from pipeline.transformation.publishing.publishers.store import PublisherStore

log = setup_logger("backfill_source_record_publishers", os.path.dirname(__file__))

_BATCH = 10_000

_RECORDS = text("""
    SELECT id, source::text AS source, doc_type::text AS doc_type, serial_id, monograph_id,
           biblio->>'publisher' AS name, publisher_id
    FROM source_records
    WHERE biblio ? 'publisher' OR publisher_id IS NOT NULL
""")

_UPDATE = text("""
    UPDATE source_records sr SET publisher_id = c.publisher_id
    FROM jsonb_to_recordset(CAST(:changes AS jsonb)) AS c(id integer, publisher_id integer)
    WHERE sr.id = c.id
""")


def changes(conn: Connection) -> list[tuple[int, int | None]]:
    """Renvoie `(id, éditeur)` des enregistrements sources à éditeur modifié. Trouve ou crée les éditeurs nommés."""
    store = PublisherStore(conn)
    publishers: dict[str, int | None] = {}
    result: list[tuple[int, int | None]] = []
    for r in conn.execute(_RECORDS).all():
        wanted = None
        has_container = r.serial_id is not None or r.monograph_id is not None
        if r.name and source_record_has_publisher(
            r.doc_type, r.source, has_container=has_container
        ):
            if r.name not in publishers:
                publishers[r.name] = find_or_create_publisher(r.name, repo=store)
            wanted = publishers[r.name]
        if wanted != r.publisher_id:
            result.append((r.id, wanted))
    return result


def apply(conn: Connection, pending: list[tuple[int, int | None]]) -> None:
    """Écrit les éditeurs et met les enregistrements sources dans la file de réconciliation, par lots."""
    for start in range(0, len(pending), _BATCH):
        batch = pending[start : start + _BATCH]
        payload = json.dumps([{"id": i, "publisher_id": p} for i, p in batch])
        conn.execute(_UPDATE, {"changes": payload})
        enqueue(
            conn,
            Queue.SOURCE_RECORD_KEYS,
            "SELECT id FROM source_records WHERE id = ANY(:ids)",
            {"ids": [i for i, _ in batch]},
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans rien écrire")
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        log.info("Lecture des noms d'éditeur des enregistrements sources…")
        pending = changes(conn)
        log.info("%d enregistrements sources changent d'éditeur", len(pending))
        if args.dry_run:
            conn.rollback()
            return 0
        apply(conn, pending)
        conn.commit()
        log.info("Écrit ; la phase publications recalcule l'éditeur de leurs publications")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
