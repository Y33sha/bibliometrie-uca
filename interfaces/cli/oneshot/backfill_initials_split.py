# STATUS: oneshot (2026-10-06)
"""Rattache à leurs informations du contributeur corrigées les contributions sources dont le nom de famille se réduit à des initiales.

Le découpage retenu d'une contribution source (`ContributorName.split`) place en prénom des initiales données comme nom de famille par la source : « Del Buono L. », « C., Küll », surname « M. » et forename « Brigante ». Ce script recalcule le découpage des contributions sources dont les informations du contributeur ont un nom fait d'initiales, et rattache chacune aux informations du contributeur de son découpage. Il précède toute normalisation de leurs enregistrements sources : la synchronisation retrouve les contributions sources en base par leurs informations du contributeur. Les lignes de `contributor_information` devenues orphelines sont purgées. Idempotent.

Usage :
    uv run python -m interfaces.cli.oneshot.backfill_initials_split            # exécution
    uv run python -m interfaces.cli.oneshot.backfill_initials_split --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, bindparam, text

from domain.persons.contributor_name import ContributorName
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.jsonb import Jsonb
from infrastructure.observability.log import setup_logger
from pipeline.ingestion.common.source_contribution_store import (
    CONTRIBUTOR_INFORMATION_KEY_COLUMNS,
    delete_orphan_contributor_information,
    key_hash_sql,
)
from pipeline.ingestion.common.source_contributions import contributor_name_fields

log = setup_logger("backfill_initials_split", os.path.dirname(__file__))

_CANDIDATES_SQL = text(r"""
    SELECT sc.id, sc.raw_author_name, sc.raw_last_name, sc.raw_first_name,
           ci.last_name_normalized, ci.first_name_normalized, ci.identifiers
    FROM source_contributions sc
    JOIN contributor_information ci ON ci.id = sc.contributor_information_id
    WHERE ci.last_name_normalized ~ '^([a-z] )*[a-z]$'
""")

_UPSERT_CONTRIBUTOR_INFORMATION_SQL = text(f"""
    INSERT INTO contributor_information ({", ".join(CONTRIBUTOR_INFORMATION_KEY_COLUMNS)})
    SELECT DISTINCT t.last_name_normalized, t.first_name_normalized, t.identifiers
    FROM jsonb_to_recordset(:payload) AS t(
        last_name_normalized text, first_name_normalized text, identifiers jsonb)
    ON CONFLICT ({", ".join(CONTRIBUTOR_INFORMATION_KEY_COLUMNS)}) DO NOTHING
""").bindparams(bindparam("payload", type_=Jsonb))

_REPOINT_SQL = text(
    """
    UPDATE source_contributions sc SET contributor_information_id = ci.id
    FROM jsonb_to_recordset(:payload) AS t(
        source_contribution_id integer, last_name_normalized text, first_name_normalized text,
        identifiers jsonb)
    JOIN contributor_information ci ON ci.key_hash = """
    + key_hash_sql([f"t.{c}" for c in CONTRIBUTOR_INFORMATION_KEY_COLUMNS])
    + """
    WHERE sc.id = t.source_contribution_id
"""
).bindparams(bindparam("payload", type_=Jsonb))


def backfill(conn: Connection, *, apply: bool) -> int:
    """Rattache les contributions sources dont le découpage change. Renvoie leur nombre."""
    payload = []
    for row in conn.execute(_CANDIDATES_SQL):
        name = ContributorName.from_columns(
            row.raw_author_name, row.raw_last_name, row.raw_first_name
        )
        fields = contributor_name_fields(name)
        split = (fields["last_name_normalized"], fields["first_name_normalized"])
        if split == (row.last_name_normalized, row.first_name_normalized):
            continue
        payload.append(
            {
                "source_contribution_id": row.id,
                "last_name_normalized": split[0],
                "first_name_normalized": split[1],
                "identifiers": row.identifiers,
            }
        )
    if apply and payload:
        conn.execute(_UPSERT_CONTRIBUTOR_INFORMATION_SQL, {"payload": payload})
        conn.execute(_REPOINT_SQL, {"payload": payload})
    return len(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    apply = not parser.parse_args().dry_run
    with get_sync_engine().connect() as conn:
        changed = backfill(conn, apply=apply)
        log.info("contributions sources au découpage corrigé : %d", changed)
        if apply:
            log.info(
                "informations du contributeur orphelines purgées : %d",
                delete_orphan_contributor_information(conn),
            )
            conn.commit()
            log.info("✓ backfill appliqué")
        else:
            log.info("DRY-RUN — aucune écriture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
