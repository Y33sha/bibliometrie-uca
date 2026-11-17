# STATUS: maintenance
"""Applique au stock la table de correspondance des types de document (`map_doc_type`), après un changement de la table. La normalisation l'applique aux enregistrements sources moissonnés ensuite.

Le type d'avant correction d'un enregistrement source se relit dans `corrections.doc_type.raw` s'il est corrigé, dans `doc_type` sinon : le type converti s'écrit au même endroit, et la phase `metadata_correction` refait la correction. Les enregistrements sources concernés passent en file de réconciliation, avec ceux de leurs publications.

Usage :
    uv run python -m interfaces.cli.maintenance.apply_doc_type_mapping [--dry-run]
    run_pipeline --from metadata_correction
"""

from __future__ import annotations

import argparse
import os
from collections import Counter, defaultdict
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.documents.doc_types import DocType
from domain.source_records.doc_types import map_doc_type
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger

log = setup_logger("apply_doc_type_mapping", os.path.dirname(__file__))

_SOURCE_RECORDS = text("""
    SELECT id, source::text AS source, raw_doc_type,
           coalesce(corrections->'doc_type'->>'raw', doc_type::text) AS stored,
           corrections->'doc_type'->>'corrected_by' IS NOT NULL AS corrected
    FROM source_records
    WHERE raw_doc_type IS NOT NULL
""")
"""Enregistrements sources à type brut, avec leur type d'avant correction."""

_UPDATE_DOC_TYPE = text("""
    UPDATE source_records SET doc_type = CAST(:doc_type AS doc_type), updated_at = clock_timestamp()
    WHERE id = ANY(:ids)
""")

_UPDATE_RAW = text("""
    UPDATE source_records
    SET corrections = jsonb_set(corrections, '{doc_type,raw}', to_jsonb(CAST(:doc_type AS text))),
        updated_at = clock_timestamp()
    WHERE id = ANY(:ids)
""")

_SOURCE_RECORDS_TO_RECONCILE = """
    SELECT unnest(CAST(:ids AS integer[]))
    UNION
    SELECT sr.id FROM source_records sr
    WHERE sr.publication_id IN (
        SELECT publication_id FROM source_records WHERE id = ANY(CAST(:ids AS integer[]))
    )
"""
"""Enregistrements sources convertis, et ceux de leurs publications."""


class _Conversion(NamedTuple):
    id: int
    source: str
    raw_doc_type: str
    stored: str
    mapped: str
    corrected: bool


def conversions(conn: Connection) -> list[_Conversion]:
    """Renvoie les enregistrements sources dont le type d'avant correction diverge de la table. Un type brut inconnu de la table donne `other`, comme à la normalisation."""
    return [
        _Conversion(r.id, r.source, r.raw_doc_type, r.stored, mapped, r.corrected)
        for r in conn.execute(_SOURCE_RECORDS)
        if (mapped := map_doc_type(r.raw_doc_type, r.source) or DocType.OTHER) != r.stored
    ]


def apply_mapping(conn: Connection, *, dry_run: bool) -> None:
    """Réécrit le type d'avant correction des enregistrements sources divergents et les marque à réconcilier."""
    found = conversions(conn)
    for (source, raw, stored, mapped), n in sorted(
        Counter((c.source, c.raw_doc_type, c.stored, c.mapped) for c in found).items(), key=str
    ):
        log.info("  %s « %s » : %s → %s (%d)", source, raw, stored, mapped, n)
    log.info("Enregistrements sources à convertir : %d", len(found))
    if dry_run or not found:
        return
    by_target: dict[tuple[str, bool], list[int]] = defaultdict(list)
    for c in found:
        by_target[(c.mapped, c.corrected)].append(c.id)
    for (doc_type, corrected), ids in by_target.items():
        conn.execute(
            _UPDATE_RAW if corrected else _UPDATE_DOC_TYPE, {"doc_type": doc_type, "ids": ids}
        )
    marked = enqueue(
        conn, Queue.SOURCE_RECORD_KEYS, _SOURCE_RECORDS_TO_RECONCILE, {"ids": [c.id for c in found]}
    )
    log.info("Marqués pour la réconciliation : %d", marked)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()
    with get_sync_engine().begin() as conn:
        apply_mapping(conn, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
