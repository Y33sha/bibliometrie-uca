# STATUS: oneshot (2026-11-03)
"""Applique au stock la correspondance des résumés de conférence : OpenAlex `conference-abstract` et WoS `Meeting Abstract` donnent `conference_abstract`.

Le type converti s'écrit là où la phase `metadata_correction` relit le type d'avant correction : `corrections.doc_type.raw` pour un enregistrement source corrigé, `doc_type` sinon. Les enregistrements sources des publications de type `conference` passent en file de réconciliation : l'arbitrage et la correction de la publication changent pour ces publications.

Usage :
    uv run python -m interfaces.cli.oneshot.requalify_conference_abstracts [--dry-run]
    run_pipeline --from metadata_correction
"""

from __future__ import annotations

import argparse
import os
from collections import Counter

from sqlalchemy import Connection, text

from domain.documents.doc_types import DocType
from domain.source_records.doc_types import map_doc_type
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger

log = setup_logger("requalify_conference_abstracts", os.path.dirname(__file__))

_CANDIDATES = text("""
    SELECT id, source::text AS source, raw_doc_type,
           corrections->'doc_type'->>'corrected_by' AS corrected_by
    FROM source_records
    WHERE source IN ('openalex', 'wos') AND raw_doc_type IS NOT NULL
      AND coalesce(corrections->'doc_type'->>'raw', doc_type::text) = 'conference'
""")
"""Enregistrements sources OpenAlex et WoS de type `conference` avant correction."""

_UPDATE_DOC_TYPE = text("""
    UPDATE source_records SET doc_type = 'conference_abstract', updated_at = clock_timestamp()
    WHERE id = ANY(:ids)
""")

_UPDATE_RAW = text("""
    UPDATE source_records
    SET corrections = jsonb_set(corrections, '{doc_type,raw}', '"conference_abstract"'),
        updated_at = clock_timestamp()
    WHERE id = ANY(:ids)
""")

_CONFERENCE_SOURCE_RECORDS = """
    SELECT sr.id FROM source_records sr
    JOIN publications p ON p.id = sr.publication_id
    WHERE p.doc_type = 'conference'
"""


def requalify(conn: Connection, *, dry_run: bool) -> None:
    """Réécrit le type des enregistrements sources de résumé de conférence et marque les enregistrements sources à réconcilier."""
    rows = [
        r
        for r in conn.execute(_CANDIDATES)
        if map_doc_type(r.raw_doc_type, r.source) == DocType.CONFERENCE_ABSTRACT
    ]
    uncorrected = [r.id for r in rows if r.corrected_by is None]
    corrected = [r.id for r in rows if r.corrected_by is not None]
    log.info(
        "Enregistrements sources : %d sans correction de type, %d corrigés",
        len(uncorrected),
        len(corrected),
    )
    for (source, rule), n in sorted(
        Counter((r.source, r.corrected_by) for r in rows).items(), key=str
    ):
        log.info("  %s, %s : %d", source, rule or "sans correction", n)
    if dry_run:
        return
    conn.execute(_UPDATE_DOC_TYPE, {"ids": uncorrected})
    conn.execute(_UPDATE_RAW, {"ids": corrected})
    marked = enqueue(
        conn,
        Queue.SOURCE_RECORD_KEYS,
        "SELECT unnest(CAST(:ids AS integer[]))",
        {"ids": uncorrected + corrected},
    )
    marked += enqueue(conn, Queue.SOURCE_RECORD_KEYS, _CONFERENCE_SOURCE_RECORDS, {})
    log.info("Marqués pour la réconciliation : %d", marked)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()
    with get_sync_engine().begin() as conn:
        requalify(conn, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
