# STATUS: oneshot (2026-10-06)
"""Rattache à leur identité corrigée les signatures dont le nom de famille se réduit à des initiales.

Le découpage retenu d'une signature (`SignatureName.split`) place en prénom des initiales que la source donne comme nom de famille : « Del Buono L. », « C., Küll », surname « M. » et forename « Brigante ». Ce script recalcule le découpage des signatures dont l'identité a un nom fait d'initiales, et rattache chacune à l'identité de son découpage. Il précède toute normalisation de leurs notices : la synchronisation des signatures rapproche par identité. Les identités devenues orphelines sont purgées. Idempotent.

Usage :
    python -m interfaces.cli.oneshot.backfill_initials_split            # exécution
    python -m interfaces.cli.oneshot.backfill_initials_split --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, bindparam, text

from application.pipeline.normalize._authorships_batch import signature_name_fields
from domain.persons.signature_name import SignatureName
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.jsonb import Jsonb
from infrastructure.observability.log import setup_logger
from infrastructure.pipeline.normalize.authorships import (
    IDENTITY_KEY_COLUMNS,
    delete_orphan_identities,
    key_hash_sql,
)

log = setup_logger("backfill_initials_split", os.path.dirname(__file__))

_CANDIDATES_SQL = text(r"""
    SELECT sa.id, sa.raw_author_name, sa.raw_last_name, sa.raw_first_name,
           aik.last_name_normalized, aik.first_name_normalized, aik.person_identifiers
    FROM source_authorships sa
    JOIN author_identifying_keys aik ON aik.id = sa.identity_id
    WHERE aik.last_name_normalized ~ '^([a-z] )*[a-z]$'
""")

_UPSERT_IDENTITIES_SQL = text(f"""
    INSERT INTO author_identifying_keys ({", ".join(IDENTITY_KEY_COLUMNS)})
    SELECT DISTINCT t.last_name_normalized, t.first_name_normalized, t.person_identifiers
    FROM jsonb_to_recordset(:payload) AS t(
        last_name_normalized text, first_name_normalized text, person_identifiers jsonb)
    ON CONFLICT ({", ".join(IDENTITY_KEY_COLUMNS)}) DO NOTHING
""").bindparams(bindparam("payload", type_=Jsonb))

_REPOINT_SQL = text(
    """
    UPDATE source_authorships sa SET identity_id = aik.id
    FROM jsonb_to_recordset(:payload) AS t(
        sa_id integer, last_name_normalized text, first_name_normalized text,
        person_identifiers jsonb)
    JOIN author_identifying_keys aik ON aik.key_hash = """
    + key_hash_sql([f"t.{c}" for c in IDENTITY_KEY_COLUMNS])
    + """
    WHERE sa.id = t.sa_id
"""
).bindparams(bindparam("payload", type_=Jsonb))


def backfill(conn: Connection, *, apply: bool) -> int:
    """Rattache les signatures dont le découpage change. Retourne leur nombre."""
    payload = []
    for row in conn.execute(_CANDIDATES_SQL):
        name = SignatureName.from_columns(
            row.raw_author_name, row.raw_last_name, row.raw_first_name
        )
        fields = signature_name_fields(name)
        split = (fields["last_name_normalized"], fields["first_name_normalized"])
        if split == (row.last_name_normalized, row.first_name_normalized):
            continue
        payload.append(
            {
                "sa_id": row.id,
                "last_name_normalized": split[0],
                "first_name_normalized": split[1],
                "person_identifiers": row.person_identifiers,
            }
        )
    if apply and payload:
        conn.execute(_UPSERT_IDENTITIES_SQL, {"payload": payload})
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
        log.info("signatures au découpage corrigé : %d", changed)
        if apply:
            log.info("identités orphelines purgées : %d", delete_orphan_identities(conn))
            conn.commit()
            log.info("✓ backfill appliqué")
        else:
            log.info("DRY-RUN — aucune écriture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
