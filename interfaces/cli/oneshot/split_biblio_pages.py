# STATUS: oneshot (2026-10-21)
"""Décompose la pagination HAL (`biblio.pages`) et Crossref (`biblio.page`) en `first_page` et `last_page`.

Le script applique aux enregistrements sources existants le découpage de leur normaliseur (`page_range` de `pipeline.ingestion.hal.normalize` et de `pipeline.ingestion.crossref.normalize`). Il recalcule ensuite leurs publications (`lifecycle.refresh`), dont `biblio` est la fusion de celui des enregistrements sources.

Usage :
    uv run python -m interfaces.cli.oneshot.split_biblio_pages [--dry-run]
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from collections.abc import Mapping

from sqlalchemy import Connection, bindparam, text

from domain.source_records.biblio import PageRange
from domain.types import JsonValue, as_str
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.jsonb import Jsonb
from infrastructure.observability.log import setup_logger
from pipeline.ingestion.crossref.normalize import page_range as crossref_page_range
from pipeline.ingestion.hal.normalize import page_range as hal_page_range
from pipeline.transformation.publications import lifecycle

log = setup_logger("split_biblio_pages", os.path.dirname(__file__))

_HAL_PAGES = "pages"
_CROSSREF_PAGE = "page"


def split_pages(
    source: str, raw_doc_type: str | None, biblio: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    """`biblio` dont la pagination HAL ou Crossref est remplacée par `first_page` et `last_page`."""
    if source == "hal":
        pages = hal_page_range(as_str(biblio.get(_HAL_PAGES)), raw_doc_type)
    else:
        pages = crossref_page_range(
            as_str(biblio.get(_CROSSREF_PAGE)), as_str(biblio.get("article_number"))
        )
    kept = {k: v for k, v in biblio.items() if k not in (_HAL_PAGES, _CROSSREF_PAGE)}
    return {**kept, **{k: v for k, v in pages._asdict().items() if v is not None}}


def plan(conn: Connection) -> tuple[list[dict[str, JsonValue]], Counter[str]]:
    """Mises à jour `{id, biblio}` des enregistrements sources, et décompte du résultat par forme."""
    rows = conn.execute(
        text(f"""
            SELECT id, source::text AS source, raw_doc_type, biblio
            FROM source_records
            WHERE (source = 'hal' AND biblio ? '{_HAL_PAGES}')
               OR (source = 'crossref' AND biblio ? '{_CROSSREF_PAGE}')
        """)
    ).all()
    updates: list[dict[str, JsonValue]] = []
    tally: Counter[str] = Counter()
    for r in rows:
        biblio = split_pages(r.source, r.raw_doc_type, r.biblio)
        pages = PageRange(as_str(biblio.get("first_page")), as_str(biblio.get("last_page")))
        tally[
            f"{r.source} : "
            + ("intervalle" if pages.last_page else "page seule" if pages.first_page else "écartée")
        ] += 1
        updates.append({"id": r.id, "biblio": biblio or None})
    return updates, tally


def apply(conn: Connection, updates: list[dict[str, JsonValue]]) -> Counter[str]:
    """Écrit `biblio` et recalcule les publications concernées. Renvoie le décompte des verdicts du recalcul."""
    conn.execute(
        text("""
            UPDATE source_records sr SET biblio = t.biblio
            FROM jsonb_to_recordset(:payload) AS t(id integer, biblio jsonb)
            WHERE sr.id = t.id
        """).bindparams(bindparam("payload", type_=Jsonb)),
        {"payload": updates},
    )
    publication_ids = conn.execute(
        text("""
            SELECT DISTINCT publication_id FROM source_records
            WHERE id = ANY(:ids) AND publication_id IS NOT NULL
        """),
        {"ids": [u["id"] for u in updates]},
    ).scalars()
    return Counter(lifecycle.refresh(conn, pid).value for pid in publication_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        updates, tally = plan(conn)
        log.info("enregistrements sources : %d, %s", len(updates), dict(sorted(tally.items())))
        if args.dry_run:
            conn.rollback()
            return 0
        verdicts = apply(conn, updates)
        conn.commit()
        log.info("publications recalculées : %s", dict(verdicts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
