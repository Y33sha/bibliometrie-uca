# STATUS: oneshot (2026-11-03)
"""Retire l'ORCID des informations du contributeur des contributions sources ScanR.

La normalisation ScanR ignore l'ORCID. Chaque contribution source ScanR à ORCID passe aux informations du contributeur de même nom sans ORCID, créées au besoin ; sa neutralisation d'ORCID disparaît. Comme à la normalisation, ses publications sont marquées pour le groupement des auteurs, et ses contributions rattachées pour la redécision de leur personne. Les phases suivantes traitent ensuite ce qui a changé :
    run_pipeline --from author_grouping

Usage :
    uv run python -m interfaces.cli.oneshot.strip_scanr_orcids [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger
from pipeline.ingestion.common.source_contribution_store import (
    CONTRIBUTOR_INFORMATION_KEY_COLUMNS,
    key_hash_sql,
)

log = setup_logger("strip_scanr_orcids", os.path.dirname(__file__))

_TARGETS = text("""
    CREATE TEMP TABLE scanr_orcid_targets AS
    SELECT sc.id, sc.source_record_id,
           ci.last_name_normalized, ci.first_name_normalized,
           nullif(ci.identifiers - 'orcid', '{}'::jsonb) AS identifiers
    FROM source_contributions sc
    JOIN contributor_information ci ON ci.id = sc.contributor_information_id
    WHERE sc.source = 'scanr' AND ci.identifiers ? 'orcid'
""")

_COUNTS = text("""
    SELECT count(*) AS source_contributions,
           count(DISTINCT source_record_id) AS source_records
    FROM scanr_orcid_targets
""")

_INSERT_CONTRIBUTOR_INFORMATION = text(f"""
    INSERT INTO contributor_information ({", ".join(CONTRIBUTOR_INFORMATION_KEY_COLUMNS)})
    SELECT DISTINCT {", ".join(CONTRIBUTOR_INFORMATION_KEY_COLUMNS)} FROM scanr_orcid_targets
    ON CONFLICT ON CONSTRAINT contributor_information_key DO NOTHING
""")

_REPOINT = text(f"""
    UPDATE source_contributions sc
    SET contributor_information_id = ci.id,
        neutralized_identifiers = nullif(sc.neutralized_identifiers - 'orcid', '{{}}'::jsonb)
    FROM scanr_orcid_targets t
    JOIN contributor_information ci
      ON ci.key_hash = {key_hash_sql([f"t.{c}" for c in CONTRIBUTOR_INFORMATION_KEY_COLUMNS])}
    WHERE sc.id = t.id
""")

_PUBLICATIONS = "SELECT sr.publication_id FROM scanr_orcid_targets t JOIN source_records sr ON sr.id = t.source_record_id WHERE sr.publication_id IS NOT NULL"

_ATTACHED_CONTRIBUTIONS = """
    SELECT g.id FROM scanr_orcid_targets t
    JOIN aligned_source_contributions gm ON gm.source_contribution_id = t.id
    JOIN contributions g ON g.id = gm.contribution_id
    WHERE g.person_id IS NOT NULL
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="rapport seul, sans écriture")
    args = parser.parse_args()
    with get_sync_engine().begin() as conn:
        conn.execute(_TARGETS)
        counts = conn.execute(_COUNTS).one()
        log.info(
            "%d contributions sources ScanR à ORCID, dans %d enregistrements sources",
            counts.source_contributions,
            counts.source_records,
        )
        if args.dry_run:
            return
        conn.execute(_INSERT_CONTRIBUTOR_INFORMATION)
        repointed = conn.execute(_REPOINT).rowcount
        log.info("%d contributions sources sans ORCID", repointed)
        grouped = enqueue(conn, Queue.PUBLICATION_CONTRIBUTIONS, _PUBLICATIONS, {})
        log.info("%d publications marquées pour le groupement des auteurs", grouped)
        resolved = enqueue(conn, Queue.CONTRIBUTION_RESOLUTION, _ATTACHED_CONTRIBUTIONS, {})
        log.info("%d contributions marquées pour la redécision de leur personne", resolved)
        log.info("Ensuite : run_pipeline --from author_grouping")


if __name__ == "__main__":
    main()
