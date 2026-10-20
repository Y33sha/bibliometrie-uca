# STATUS: oneshot (2026-10-19)
"""Décode les accents LaTeX des noms d'auteur du stock (« Bayart, Fr\\'ed\\'eric » → « Bayart, Frédéric »), comme le fait la normalisation (`clean_raw_author_name`).

Chaque signature dont le nom contient une commande LaTeX reçoit son nom nettoyé et l'identité qui en découle (`contributor_information`, identifiants inchangés). Sa personne, créée sous le nom illisible, est détachée, sauf épinglage : la phase `persons` la résout à nouveau et supprime les personnes vidées. Les décomptes d'auteurs des notices touchées sont recalculés et leurs publications sont à regrouper. Les identités devenues orphelines sont supprimées.

Usage :
    python -m interfaces.cli.oneshot.decode_latex_author_names [--dry-run]
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping

from sqlalchemy import Connection, TextClause, bindparam, text

from domain.persons.signature_name import SignatureName
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.jsonb import Jsonb
from infrastructure.observability.log import setup_logger
from interfaces.cli.oneshot.backfill_author_counts import backfill_notices
from pipeline.ingestion.common.signature_queries import (
    IDENTITY_KEY_COLUMNS,
    delete_orphan_identities,
    key_hash_sql,
)
from pipeline.ingestion.common.signatures import signature_name_fields

log = setup_logger("decode_latex_author_names", os.path.dirname(__file__))


def candidates_sql(condition: str) -> TextClause:
    """Signatures candidates : celles dont les noms réunis (`n.names`) vérifient `condition`."""
    return text(f"""
        SELECT sa.id, sa.source_record_id AS notice, sa.raw_author_name, sa.raw_last_name,
               sa.raw_first_name, aik.identifiers
        FROM source_contributions sa JOIN contributor_information aik ON aik.id = sa.contributor_information_id
        CROSS JOIN LATERAL (
            SELECT concat_ws(' ', sa.raw_author_name, sa.raw_last_name, sa.raw_first_name) AS names
        ) n
        WHERE {condition}
    """)


_LATEX_CANDIDATES_SQL = candidates_sql("strpos(n.names, chr(92)) > 0")

_UPSERT_IDENTITIES_SQL = text(f"""
    INSERT INTO contributor_information ({", ".join(IDENTITY_KEY_COLUMNS)})
    SELECT DISTINCT t.last_name_normalized, t.first_name_normalized, t.identifiers
    FROM jsonb_to_recordset(:payload) AS t(
        last_name_normalized text, first_name_normalized text, identifiers jsonb)
    ON CONFLICT ({", ".join(IDENTITY_KEY_COLUMNS)}) DO NOTHING
""").bindparams(bindparam("payload", type_=Jsonb))

_UPDATE_SIGNATURES_SQL = text(
    """
    UPDATE source_contributions sa
    SET raw_author_name = t.raw_author_name, raw_last_name = t.raw_last_name,
        raw_first_name = t.raw_first_name, contributor_information_id = aik.id,
        person_id = CASE WHEN ca.source_contribution_id IS NULL THEN NULL ELSE sa.person_id END,
        resolution_mode = CASE WHEN ca.source_contribution_id IS NULL THEN NULL ELSE sa.resolution_mode END
    FROM jsonb_to_recordset(:payload) AS t(
        id integer, raw_author_name text, raw_last_name text, raw_first_name text,
        last_name_normalized text, first_name_normalized text, identifiers jsonb)
    JOIN contributor_information aik ON aik.key_hash = """
    + key_hash_sql([f"t.{c}" for c in IDENTITY_KEY_COLUMNS])
    + """
    LEFT JOIN confirmed_source_contributions ca ON ca.source_contribution_id = t.id
    WHERE sa.id = t.id
"""
).bindparams(bindparam("payload", type_=Jsonb))

_MARK_DIRTY_SQL = text("""
    UPDATE publications p SET contributions_dirty = true
    FROM source_records sp
    WHERE sp.id = ANY(:notices) AND p.id = sp.publication_id AND NOT p.contributions_dirty
""")


def decoded_names(
    conn: Connection,
    candidates: TextClause = _LATEX_CANDIDATES_SQL,
    params: Mapping[str, object] | None = None,
) -> tuple[list[dict[str, object]], list[int]]:
    """Signatures `candidates` dont le nom nettoyé diffère du nom stocké, avec leurs nouvelles colonnes de nom, et leurs notices."""
    rows: list[dict[str, object]] = []
    notices: set[int] = set()
    for r in conn.execute(candidates, params or {}):
        name = (
            SignatureName.from_parts(r.raw_last_name, r.raw_first_name)
            if r.raw_last_name is not None
            else SignatureName.from_raw(r.raw_author_name)
        )
        if name is None:
            continue
        fields = signature_name_fields(name)
        if (fields["raw_author_name"], fields["raw_last_name"], fields["raw_first_name"]) == (
            r.raw_author_name,
            r.raw_last_name,
            r.raw_first_name,
        ):
            continue
        rows.append({"id": r.id, **fields, "identifiers": r.identifiers})
        notices.add(r.notice)
    return rows, sorted(notices)


def decode(conn: Connection, rows: list[dict[str, object]], notices: list[int]) -> int:
    """Écrit les noms décodés et leurs identités, détache les personnes, met à jour les notices et les publications. Rend le nombre d'identités orphelines supprimées."""
    conn.execute(_UPSERT_IDENTITIES_SQL, {"payload": rows})
    conn.execute(_UPDATE_SIGNATURES_SQL, {"payload": rows})
    backfill_notices(conn, notices)
    conn.execute(_MARK_DIRTY_SQL, {"notices": notices})
    return delete_orphan_identities(conn)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        rows, notices = decoded_names(conn)
        log.info("signatures à décoder : %d, dans %d notices", len(rows), len(notices))
        for row in rows[:5]:
            log.info(
                "  %s / %s / %s",
                row["raw_author_name"],
                row["raw_last_name"],
                row["raw_first_name"],
            )
        if args.dry_run or not rows:
            conn.rollback()
            return 0
        orphans = decode(conn, rows, notices)
        conn.commit()
        log.info(
            "signatures décodées : %d ; identités orphelines supprimées : %d", len(rows), orphans
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
