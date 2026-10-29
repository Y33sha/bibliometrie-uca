# STATUS: oneshot (2026-10-29)
"""Écrit dans `source_record_identifiers` le DOI des enregistrements sources sans payload au raw store.

`fill_source_record_identifiers` lit chaque payload au raw store. Un enregistrement source sans payload garde son DOI dans la colonne `doi`, absent de la table. Ce script écrit ce DOI d'avant correction, avec le rôle que la normalisation de sa source donne au DOI : primaire chez Crossref et DataCite, dérivé chez ScanR quand l'identifiant ScanR le contient, secondaire ailleurs. Un DOI retiré par la correction par DOI partagé est écrit retiré, sous la même règle.

Usage :
    python -m interfaces.cli.oneshot.fill_missing_source_record_dois [--dry-run]
"""

from __future__ import annotations

import argparse
import os
from collections import Counter

from sqlalchemy import Connection, text

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
    normalize_identifiers,
)
from domain.source_records.metadata_correction.shared_doi import DoiClusterCase
from domain.sources.registry import Source
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.ingestion.scanr.payload import scanr_derived_identifier

log = setup_logger("fill_missing_source_record_dois", os.path.dirname(__file__))

# Règles de retrait de la correction par DOI partagé.
_REMOVAL_RULES = frozenset(case.value for case in DoiClusterCase)

# Rôle du DOI dans un enregistrement source, par source, hors identifiant ScanR dérivé.
_ROLE = {
    Source.CROSSREF: SourceIdentifierRole.PRIMARY,
    Source.DATACITE: SourceIdentifierRole.PRIMARY,
}

_ROWS = text("""
    SELECT sr.id, sr.source::text AS source, sr.source_id, sr.doi,
           sr.corrections -> 'doi' ->> 'raw' AS raw_doi,
           sr.corrections -> 'doi' ->> 'corrected_by' AS corrected_by
    FROM source_records sr
    WHERE COALESCE(sr.corrections -> 'doi' ->> 'raw', sr.doi) IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM source_record_identifiers i
          WHERE i.source_record_id = sr.id AND i.id_type = 'doi'
      )
    ORDER BY sr.id
""")

_INSERT = text("""
    INSERT INTO source_record_identifiers (source_record_id, id_type, id_value, role, removed_by)
    VALUES (:source_record_id, 'doi', :id_value, :role, :removed_by)
    ON CONFLICT DO NOTHING
""")


def _role(source: str, source_id: str, doi: str) -> SourceIdentifierRole:
    if source == Source.SCANR:
        derived = scanr_derived_identifier(source_id)
        if derived is not None and derived.id_type is SourceIdentifierType.DOI:
            normalized, _ = normalize_identifiers([derived])
            if normalized and normalized[0].value == doi:
                return SourceIdentifierRole.DERIVED
    return _ROLE.get(Source(source), SourceIdentifierRole.SECONDARY)


def _identifiers(conn: Connection) -> tuple[list[dict[str, object]], Counter[str], int]:
    """Lignes à écrire, leur décompte par source et rôle, et le nombre de DOI invalides."""
    rows: list[dict[str, object]] = []
    counts: Counter[str] = Counter()
    invalid = 0
    for r in conn.execute(_ROWS):
        removed_by = r.corrected_by if r.doi is None and r.raw_doi is not None else None
        if removed_by not in _REMOVAL_RULES:
            removed_by = None
        raw = r.raw_doi if r.raw_doi is not None else r.doi
        normalized, _ = normalize_identifiers(
            [SourceIdentifier(SourceIdentifierType.DOI, raw, SourceIdentifierRole.SECONDARY)]
        )
        if not normalized:
            invalid += 1
            continue
        doi = normalized[0].value
        role = _role(r.source, r.source_id, doi)
        rows.append(
            {
                "source_record_id": r.id,
                "id_value": doi,
                "role": role.value,
                "removed_by": removed_by,
            }
        )
        counts[f"{r.source} {role.value}{' retiré' if removed_by else ''}"] += 1
    return rows, counts, invalid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte les DOI sans rien écrire")
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        rows, counts, invalid = _identifiers(conn)
        for key, n in sorted(counts.items()):
            log.info("%s : %d", key, n)
        log.info("%d DOI à écrire, %d DOI invalides écartés", len(rows), invalid)
        if args.dry_run:
            log.info("Dry-run, rien écrit.")
            return
        if rows:
            conn.execute(_INSERT, rows)
        conn.commit()
        log.info("%d DOI écrits", len(rows))


if __name__ == "__main__":
    main()
