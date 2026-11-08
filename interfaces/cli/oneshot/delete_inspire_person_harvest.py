# STATUS: oneshot (2026-11-07)
"""Supprime, avec leur ligne de `staging`, les enregistrements sources INSPIRE-HEP moissonnés par ORCID.

Le moissonnage d'INSPIRE-HEP cherche seulement les fiches affiliées à une institution du périmètre. Une fiche supprimée et affiliée à une institution du périmètre revient au moissonnage suivant.

Usage :
    uv run python -m interfaces.cli.oneshot.delete_inspire_person_harvest [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from domain.sources.registry import Source
from domain.sources.staging import StagingEntryMode
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.ingestion.common.source_records import delete_staged_documents

log = setup_logger("delete_inspire_person_harvest", os.path.dirname(__file__))

_TARGETS_SQL = text("""
    SELECT st.id
    FROM staging st
    WHERE st.source = :source AND st.entry_mode = :entry_mode
""")


def find_targets(conn: Connection) -> list[int]:
    """Renvoie les lignes de `staging` des fiches INSPIRE-HEP moissonnées par ORCID."""
    return list(
        conn.execute(
            _TARGETS_SQL,
            {
                "source": Source.INSPIRE.value,
                "entry_mode": StagingEntryMode.PERSON_IDENTIFIER.value,
            },
        ).scalars()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        staging_ids = find_targets(conn)
    log.info("Fiches INSPIRE-HEP moissonnées par ORCID : %d", len(staging_ids))
    if not staging_ids or args.dry_run:
        return 0

    with engine.begin() as conn:
        deleted, staged = delete_staged_documents(conn, staging_ids)
    log.info("Supprimés : %d enregistrements sources, %d lignes de staging", deleted, staged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
