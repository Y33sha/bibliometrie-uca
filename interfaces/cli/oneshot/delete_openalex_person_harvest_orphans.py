# STATUS: oneshot (2026-11-01)
"""Supprime, avec leur ligne de `staging`, les enregistrements sources OpenAlex moissonnés par ORCID sans l'ORCID déposé d'une personne à fiche RH, restés sans publication et hors périmètre.

Le moissonnage OpenAlex par personne filtre sur l'ORCID déposé (`raw_orcid`), seul retenu par la normalisation : il écarte ces enregistrements sources.

Usage :
    uv run python -m interfaces.cli.oneshot.delete_openalex_person_harvest_orphans [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from domain.persons.identifiers import AttributionStatus, PersonIdentifierType
from domain.sources.staging import StagingEntryMode
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.ingestion.common.source_records import delete_staged_documents

log = setup_logger("delete_openalex_person_harvest_orphans", os.path.dirname(__file__))

_ORCID = PersonIdentifierType.ORCID.value

_TARGETS_SQL = text(f"""
    SELECT sr.staging_id, sr.author_count
    FROM source_records sr
    JOIN staging st ON st.id = sr.staging_id
    WHERE sr.source = 'openalex'
      AND st.entry_mode = '{StagingEntryMode.PERSON_IDENTIFIER.value}'
      AND sr.publication_id IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM source_contributions sc
          WHERE sc.source_record_id = sr.id AND sc.in_perimeter
      )
      AND NOT EXISTS (
          SELECT 1
          FROM source_contributions sc
          JOIN contributor_information ci ON ci.id = sc.contributor_information_id
          JOIN person_identifiers pi
            ON pi.id_type = '{_ORCID}' AND pi.id_value = ci.identifiers ->> '{_ORCID}'
          JOIN hr_records r ON r.person_id = pi.person_id
          WHERE sc.source_record_id = sr.id
            AND pi.status <> '{AttributionStatus.REJECTED.value}'
      )
""")


def find_targets(conn: Connection) -> tuple[list[int], int]:
    """Renvoie les lignes de `staging` des enregistrements sources visés, et leur nombre de contributions sources."""
    rows = conn.execute(_TARGETS_SQL).all()
    return [r.staging_id for r in rows], sum(r.author_count for r in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        staging_ids, source_contributions = find_targets(conn)
    log.info(
        "Enregistrements sources visés : %d, %d contributions sources",
        len(staging_ids),
        source_contributions,
    )
    if not staging_ids or args.dry_run:
        return 0

    with engine.begin() as conn:
        deleted, staged = delete_staged_documents(conn, staging_ids)
    log.info("Supprimés : %d enregistrements sources, %d lignes de staging", deleted, staged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
