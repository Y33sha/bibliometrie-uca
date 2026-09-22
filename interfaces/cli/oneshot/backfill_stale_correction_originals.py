# STATUS: oneshot (2026-09-22)
"""Aligne sur la notice actuelle les valeurs d'origine périmées de `raw_metadata`.

Pour `doc_type` et `oa_status`, le script compare la valeur d'origine gardée dans `raw_metadata` à celle que la normalisation tire de la notice du raw store. Là où elles diffèrent, la colonne reçoit la valeur de la notice et la valeur d'origine est retirée. La phase `metadata_correction` refait ensuite la correction.

Usage :
    python -m interfaces.cli.oneshot.backfill_stale_correction_originals [--dry-run]
    run_pipeline --from metadata_correction
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Mapping

from sqlalchemy import text

from application.pipeline.normalize import (
    normalize_datacite,
    normalize_hal,
    normalize_openalex,
    normalize_scanr,
    normalize_wos,
)
from domain.sources.openalex import parse_primary_location
from domain.types import JsonValue, as_mapping
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store.factory import get_raw_store

log = setup_logger("backfill_stale_correction_originals", os.path.dirname(__file__))

_FIELDS = ("doc_type", "oa_status")

_RECORDS = text("""
    SELECT id, source::text AS source, source_id, doi, raw_metadata
    FROM source_publications
    WHERE raw_metadata ?| array['doc_type', 'oa_status'] AND source <> 'theses'
""")


def _fresh(source: str, payload: Mapping[str, JsonValue], doi: str | None) -> dict[str, object]:
    """`doc_type` et `oa_status` que la normalisation tire de la notice."""
    if source == "crossref":
        return {"doc_type": payload.get("type"), "oa_status": None}
    if source == "datacite":
        attributes = as_mapping(payload.get("attributes"))
        return {
            "doc_type": normalize_datacite.extract_datacite_doc_type_token(attributes),
            "oa_status": None,
        }
    if source == "hal":
        metadata = normalize_hal.extract_pub_metadata(payload, None)
    elif source == "openalex":
        metadata = normalize_openalex.extract_pub_metadata(
            payload, None, parse_primary_location(payload)
        )
    elif source == "scanr":
        metadata = normalize_scanr.extract_pub_metadata(payload, None)
    else:
        metadata = normalize_wos.extract_pub_metadata(
            normalize_wos.extract_from_api(payload, doi), None
        )
    return {"doc_type": metadata.doc_type, "oa_status": metadata.oa_status}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte sans rien modifier.")
    args = parser.parse_args()

    store = get_raw_store()
    engine = get_sync_engine()
    updates: list[dict[str, object]] = []
    stale: Counter[tuple[str, str]] = Counter()
    # Lecture par paquets : les lignes ne sont pas chargées d'un coup.
    with engine.connect() as conn:
        rows = conn.execution_options(stream_results=True, yield_per=2000).execute(_RECORDS)
        for read, row in enumerate(rows, start=1):
            if read % 10_000 == 0:
                log.info("%d notices lues, %d valeurs périmées", read, len(updates))
            try:
                payload = json.loads(store.get(row.source, row.source_id))
            except KeyError:
                continue
            fresh = _fresh(row.source, as_mapping(payload), row.doi)
            for field in _FIELDS:
                if field in row.raw_metadata and row.raw_metadata[field].get("raw") != fresh[field]:
                    stale[(row.source, field)] += 1
                    updates.append({"id": row.id, "field": field, "value": fresh[field]})

    for (source, field), n in sorted(stale.items()):
        log.info("%-9s %-10s %6d valeurs d'origine périmées", source, field, n)
    if args.dry_run or not updates:
        log.info("Rien d'écrit." if args.dry_run else "Aucune valeur périmée.")
        return 0

    with engine.begin() as conn:
        for field in _FIELDS:
            batch = [{"id": u["id"], "value": u["value"]} for u in updates if u["field"] == field]
            if batch:
                conn.execute(
                    text(
                        f"UPDATE source_publications SET {field} = :value,"  # noqa: S608
                        f" raw_metadata = raw_metadata - '{field}', keys_dirty = true"
                        " WHERE id = :id"
                    ),
                    batch,
                )
    log.info("%d valeurs alignées ; relancer run_pipeline --from metadata_correction", len(updates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
