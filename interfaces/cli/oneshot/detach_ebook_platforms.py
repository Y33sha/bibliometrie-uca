# STATUS: oneshot (2026-10-26)
"""Détache du stock les plateformes d'ebooks, qui ne sont le conteneur d'aucun document (`domain.serials.titles.names_ebook_platform`).

Les enregistrements sources rattachés à une revue sans ISSN au titre de plateforme d'ebooks perdent cette revue. Ceux dont le titre de conteneur est un titre de plateforme d'ebooks le perdent. Les uns et les autres passent dans la file de réconciliation : la phase `publications` recalcule ensuite la revue et le titre de conteneur de leurs publications, et la phase `finalize` supprime les revues devenues vides. Idempotent.

Usage :
    uv run python -m interfaces.cli.oneshot.detach_ebook_platforms [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from domain.serials.titles import names_ebook_platform
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger

log = setup_logger("detach_ebook_platforms", os.path.dirname(__file__))


def ebook_platform_serials(conn: Connection) -> list[int]:
    """Revues sans ISSN au titre de plateforme d'ebooks."""
    rows = conn.execute(
        text("""
            SELECT s.id, s.title FROM serials s
            WHERE s.title LIKE '%eBooks'
              AND NOT EXISTS (SELECT 1 FROM serial_issns i WHERE i.serial_id = s.id)
        """)
    ).all()
    return [r.id for r in rows if names_ebook_platform(r.title)]


def ebook_platform_container_records(conn: Connection) -> list[int]:
    """Enregistrements sources dont le titre de conteneur est un titre de plateforme d'ebooks."""
    rows = conn.execute(
        text("SELECT id, container_title FROM source_records WHERE container_title LIKE '%eBooks'")
    ).all()
    return [r.id for r in rows if names_ebook_platform(r.container_title)]


_DETACH_SERIALS = text(
    "UPDATE source_records SET serial_id = NULL WHERE serial_id = ANY(:serial_ids) RETURNING id"
)


def detach(conn: Connection, serial_ids: list[int], record_ids: list[int]) -> tuple[int, int, int]:
    """Retire les revues `serial_ids` de leurs enregistrements sources, et le titre de conteneur des enregistrements `record_ids`, puis les met en file. Renvoie le nombre d'enregistrements détachés de leur revue, privés de leur titre de conteneur, et mis en file."""
    detached = conn.execute(_DETACH_SERIALS, {"serial_ids": serial_ids}).scalars().all()
    cleared = conn.execute(
        text("UPDATE source_records SET container_title = NULL WHERE id = ANY(:ids)"),
        {"ids": record_ids},
    ).rowcount
    queued = enqueue(
        conn,
        Queue.SOURCE_RECORD_KEYS,
        "SELECT unnest(CAST(:ids AS int[]))",
        {"ids": sorted({*detached, *record_ids})},
    )
    return len(detached), cleared, queued


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans rien écrire")
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        serial_ids = ebook_platform_serials(conn)
        detached, cleared, queued = detach(conn, serial_ids, ebook_platform_container_records(conn))
        log.info(
            "%d revues de plateforme d'ebooks : %d enregistrements sources détachés, "
            "%d titres de conteneur retirés, %d enregistrements sources à réconcilier",
            len(serial_ids),
            detached,
            cleared,
            queued,
        )
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
