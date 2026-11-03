# STATUS: oneshot (2026-11-03)
"""Écrit dans `biblio` l'éditeur et la monographie des enregistrements sources déjà normalisés : `publisher`, `publisher_openalex_id` et `monograph`.

Le payload de chaque enregistrement source est relu au raw store. Le normaliseur de sa source en tire l'éditeur (`publisher`) et le volume (`series_and_volume`). Seules ces trois clés de `biblio` sont réécrites. Sans payload au raw store, la monographie vient de la monographie rattachée, et l'identifiant OpenAlex de l'éditeur, pour un enregistrement source OpenAlex, de l'éditeur rattaché.

Usage :
    uv run python -m interfaces.cli.oneshot.fill_biblio_publisher_and_monograph [--sources hal,openalex] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
from typing import NamedTuple

from sqlalchemy import Connection, Row, text

from domain.serials.containers import VolumeDescription
from domain.source_records.biblio import BiblioKey, with_monograph, with_publisher
from domain.sources.registry import SOURCE_PRIORITY, Source
from domain.types import JsonValue
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store import RawStore, UnreadablePayloadError, get_raw_store
from pipeline.ingestion.common.normalize import normalizer_builders
from pipeline.ingestion.common.normalizer import Document, SourceNormalizer
from pipeline.ingestion.common.staging import StagingRow

log = setup_logger("fill_biblio_publisher_and_monograph", os.path.dirname(__file__))

_BATCH = 1000

_COUNT = text("SELECT count(*) FROM source_records WHERE source = :source")

_BATCH_ROWS = text("""
    SELECT sr.id, sr.source_id, sr.biblio, st.id AS staging_id, st.doi,
           m.title AS monograph_title, m.isbn, m.eisbn, m.proceedings, m.year,
           p.openalex_id AS publisher_openalex_id
    FROM source_records sr
    LEFT JOIN staging st ON st.id = sr.staging_id
    LEFT JOIN monographs m ON m.id = sr.monograph_id
    LEFT JOIN publishers p ON p.id = sr.publisher_id
    WHERE sr.source = :source AND sr.id > :after
    ORDER BY sr.id
    LIMIT :limit
""")

_WRITE = text("""
    UPDATE source_records sr SET biblio = t.biblio
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(id integer, biblio jsonb)
    WHERE sr.id = t.id AND sr.biblio IS DISTINCT FROM t.biblio
""")


class FillStats(NamedTuple):
    """Bilan d'une source."""

    written: int
    """Enregistrements sources au `biblio` réécrit."""
    from_links: int
    """Enregistrements sources sans payload au raw store, complétés d'après leurs rattachements."""
    refused: int
    """Enregistrements sources au payload refusé par la normalisation, laissés en l'état."""


def _payload(store: RawStore, source: str, source_id: str) -> dict[str, JsonValue] | None:
    """Renvoie le payload du raw store, ou `None` sans payload lisible."""
    try:
        return json.loads(store.get(source, source_id))
    except KeyError, UnreadablePayloadError, ValueError:
        return None


def _from_payload(
    normalizer: SourceNormalizer, r: Row, row: StagingRow, doc: Document
) -> JsonValue | None:
    """Renvoie `biblio` complété d'après le document lu dans le payload ; `None` sans aucune valeur."""
    publisher = normalizer.publisher(doc)
    _, volume = normalizer.series_and_volume(row, doc)
    biblio = with_publisher(
        r.biblio,
        publisher.name if publisher else None,
        publisher.openalex_id if publisher else None,
    )
    return with_monograph(biblio, volume)


def _from_links(source: str, r: Row) -> JsonValue:
    """Renvoie `biblio` complété d'après la monographie et l'éditeur rattachés. Le nom de l'éditeur reste celui de `biblio`."""
    volume = (
        VolumeDescription(
            title=r.monograph_title,
            isbns=(r.isbn,) if r.isbn else (),
            eisbns=(r.eisbn,) if r.eisbn else (),
            proceedings=bool(r.proceedings),
            year=r.year,
        )
        if r.monograph_title or r.isbn or r.eisbn
        else None
    )
    name = (r.biblio or {}).get(BiblioKey.PUBLISHER)
    openalex_id = r.publisher_openalex_id if source == Source.OPENALEX else None
    return with_monograph(with_publisher(r.biblio, name, openalex_id), volume)


def fill_source(
    conn: Connection, source: str, store: RawStore, *, commit: bool = True
) -> FillStats:
    """Complète `biblio` des enregistrements sources de `source`, par lots. `commit` valide chaque lot."""
    normalizer = normalizer_builders(archive=False)[source](conn, log)
    written = from_links = refused = seen = 0
    after = 0
    while rows := conn.execute(
        _BATCH_ROWS, {"source": source, "after": after, "limit": _BATCH}
    ).all():
        batch: list[dict[str, object]] = []
        for r in rows:
            raw_data = _payload(store, source, r.source_id)
            if raw_data is None:
                from_links += 1
                batch.append({"id": r.id, "biblio": _from_links(source, r)})
                continue
            row = StagingRow(id=r.staging_id, source_id=r.source_id, doi=r.doi, raw_data=raw_data)
            doc = normalizer.parse(row)
            if doc is None:
                refused += 1
                continue
            batch.append({"id": r.id, "biblio": _from_payload(normalizer, r, row, doc)})
        if batch:
            written += conn.execute(_WRITE, {"rows": json.dumps(batch)}).rowcount
        if commit:
            conn.commit()
        seen += len(rows)
        after = rows[-1].id
        log.info("%s : %d traités", source, seen)
    return FillStats(written, from_links, refused)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources",
        help="Sources à traiter, séparées par des virgules. Toutes par défaut.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compte les cibles sans rien écrire")
    args = parser.parse_args()
    sources = args.sources.split(",") if args.sources else [s.value for s in SOURCE_PRIORITY]
    with get_sync_engine().connect() as conn:
        if args.dry_run:
            for source in sources:
                log.info(
                    "%s : %d enregistrements sources à traiter",
                    source,
                    conn.execute(_COUNT, {"source": source}).scalar_one(),
                )
            log.info("Dry-run, rien écrit.")
            return
        store = get_raw_store()
        for source in sources:
            stats = fill_source(conn, source, store)
            log.info(
                "%s : %d biblio réécrits, dont %d d'après les rattachements faute de payload au raw store, %d refusés par la normalisation",
                source,
                stats.written,
                stats.from_links,
                stats.refused,
            )


if __name__ == "__main__":
    main()
