# STATUS: oneshot (2026-10-31)
"""Nettoie les titres et les résumés stockés des enregistrements sources, comme la normalisation à leur écriture : entités HTML décodées, barres obliques multipliées ramenées à une, accents LaTeX hors formule convertis, espacement réduit.

Le script écrit les valeurs nettoyées, et le titre normalisé avec le titre, puis met les enregistrements sources modifiés en file de réconciliation. La phase `publications` suivante recalcule leurs publications, titre et résumé compris. Idempotent.

Usage :
    uv run python -m interfaces.cli.oneshot.clean_source_record_texts            # exécution
    uv run python -m interfaces.cli.oneshot.clean_source_record_texts --dry-run  # rapport seul
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
from pipeline.ingestion.common.source_records import stored_abstract

log = setup_logger("clean_source_record_texts", os.path.dirname(__file__))

_EXAMPLES = 5
_STREAM = 10_000
_BATCH = 1_000


def _changed_titles(conn: Connection) -> list[dict[str, object]]:
    """Renvoie les enregistrements sources dont le titre nettoyé diffère du titre stocké, avec leur titre nettoyé et normalisé."""
    rows = conn.execute(
        text("SELECT id, title FROM source_records"),
        execution_options={"stream_results": True, "yield_per": _STREAM},
    )
    return [
        {"id": row.id, "before": row.title, "after": cleaned, "tn": normalized_title(cleaned)}
        for row in rows
        if (cleaned := clean_publication_title(row.title)) != row.title
    ]


def _changed_abstracts(conn: Connection) -> list[dict[str, object]]:
    """Renvoie les enregistrements sources dont le résumé nettoyé diffère du résumé stocké, avec leur résumé nettoyé."""
    rows = conn.execute(
        text("SELECT id, abstract FROM source_records WHERE abstract IS NOT NULL"),
        execution_options={"stream_results": True, "yield_per": _STREAM},
    )
    return [
        {"id": row.id, "before": row.abstract, "after": cleaned}
        for row in rows
        if (cleaned := stored_abstract(row.abstract)) != row.abstract
    ]


def _write(
    conn: Connection, assignments: str, columns: str, payload: list[dict[str, object]]
) -> None:
    """Écrit `payload` par lots : `assignments` affecte les colonnes de `source_records` depuis les champs `columns` de chaque élément."""
    statement = text(
        f"UPDATE source_records sr SET {assignments}"
        f" FROM jsonb_to_recordset(:payload) AS p(id int, {columns})"
        " WHERE sr.id = p.id"
    ).bindparams(bindparam("payload", type_=Jsonb))
    for start in range(0, len(payload), _BATCH):
        conn.execute(statement, {"payload": payload[start : start + _BATCH]})


def _report(label: str, changed: list[dict[str, object]]) -> None:
    log.info("%d %s à nettoyer", len(changed), label)
    for c in changed[:_EXAMPLES]:
        log.info("    · %r → %r", str(c["before"])[:80], str(c["after"])[:80])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="rapport seul, sans écriture")
    args = parser.parse_args()

    with get_sync_engine().begin() as conn:
        log.info("Lecture des titres et des résumés des enregistrements sources…")
        titles = _changed_titles(conn)
        abstracts = _changed_abstracts(conn)
        _report("titres", titles)
        _report("résumés", abstracts)
        if args.dry_run or not (titles or abstracts):
            return
        log.info("Écriture des titres et des résumés…")
        _write(
            conn,
            "title = p.after, title_normalized = p.tn",
            "after text, tn text",
            [{"id": c["id"], "after": c["after"], "tn": c["tn"]} for c in titles],
        )
        _write(
            conn,
            "abstract = p.after",
            "after text",
            [{"id": c["id"], "after": c["after"]} for c in abstracts],
        )
        ids = list({c["id"] for c in titles} | {c["id"] for c in abstracts})
        enqueue(conn, Queue.SOURCE_RECORD_KEYS, "SELECT unnest(CAST(:ids AS int[]))", {"ids": ids})
        log.info("%d enregistrements sources en file de réconciliation", len(ids))


if __name__ == "__main__":
    main()
