# STATUS: oneshot (2026-10-31)
"""Nettoie les titres stockés des enregistrements sources avec `clean_publication_title`, appliqué par la normalisation à l'écriture du titre : entités HTML décodées, barres obliques multipliées ramenées à une, espacement réduit.

Le script écrit le titre nettoyé et son titre normalisé, puis met les enregistrements sources modifiés en file de réconciliation. La phase `publications` suivante recalcule leurs publications, titre compris. Idempotent.

Usage :
    uv run python -m interfaces.cli.oneshot.clean_source_record_titles            # exécution
    uv run python -m interfaces.cli.oneshot.clean_source_record_titles --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, bindparam, text

from domain.publications.metadata import clean_publication_title, normalized_title
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger

log = setup_logger("clean_source_record_titles", os.path.dirname(__file__))

_EXAMPLES = 5
_STREAM = 10_000
_BATCH = 5_000


def _changed_titles(conn: Connection) -> list[dict[str, object]]:
    """Renvoie les enregistrements sources dont le titre nettoyé diffère du titre stocké, avec leur titre nettoyé et normalisé."""
    rows = conn.execute(
        text("SELECT id, title FROM source_records"),
        execution_options={"stream_results": True, "yield_per": _STREAM},
    )
    changed: list[dict[str, object]] = []
    for row in rows:
        cleaned = clean_publication_title(row.title)
        if cleaned != row.title:
            changed.append(
                {
                    "id": row.id,
                    "before": row.title,
                    "title": cleaned,
                    "tn": normalized_title(cleaned),
                }
            )
    return changed


def _write(conn: Connection, changed: list[dict[str, object]]) -> None:
    """Écrit les titres nettoyés et met les enregistrements sources en file de réconciliation."""
    statement = text(
        "UPDATE source_records sr SET title = p.title, title_normalized = p.tn"
        " FROM jsonb_to_recordset(:payload) AS p(id int, title text, tn text)"
        " WHERE sr.id = p.id"
    ).bindparams(bindparam("payload", type_=Jsonb))
    for start in range(0, len(changed), _BATCH):
        batch = changed[start : start + _BATCH]
        conn.execute(
            statement, {"payload": [{k: c[k] for k in ("id", "title", "tn")} for c in batch]}
        )
    enqueue(
        conn,
        Queue.SOURCE_RECORD_KEYS,
        "SELECT unnest(CAST(:ids AS int[]))",
        {"ids": [c["id"] for c in changed]},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="rapport seul, sans écriture")
    args = parser.parse_args()

    with get_sync_engine().begin() as conn:
        log.info("Lecture des titres des enregistrements sources…")
        changed = _changed_titles(conn)
        log.info("%d titres à nettoyer", len(changed))
        for c in changed[:_EXAMPLES]:
            log.info("    · %r → %r", str(c["before"])[:80], str(c["title"])[:80])
        if args.dry_run or not changed:
            return
        log.info("Écriture des titres et mise en file de réconciliation…")
        _write(conn, changed)
        log.info("%d enregistrements sources en file de réconciliation", len(changed))


if __name__ == "__main__":
    main()
