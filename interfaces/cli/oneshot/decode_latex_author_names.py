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

from domain.persons.contributor_name import ContributorName
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.jsonb import Jsonb
from infrastructure.observability.log import setup_logger
from interfaces.cli.oneshot.backfill_author_counts import backfill_source_records
from pipeline.ingestion.common.source_contribution_queries import (
    CONTRIBUTOR_INFORMATION_KEY_COLUMNS,
    delete_orphan_contributor_information,
    key_hash_sql,
)
from pipeline.ingestion.common.source_contributions import contributor_name_fields

log = setup_logger("decode_latex_author_names", os.path.dirname(__file__))


def candidates_sql(condition: str) -> TextClause:
    """Signatures candidates : celles dont les noms réunis (`n.names`) vérifient `condition`."""
    return text(f"""
        SELECT sc.id, sc.source_record_id AS source_record, sc.raw_author_name, sc.raw_last_name,
               sc.raw_first_name, ci.identifiers
        FROM source_contributions sc JOIN contributor_information ci ON ci.id = sc.contributor_information_id
        CROSS JOIN LATERAL (
            SELECT concat_ws(' ', sc.raw_author_name, sc.raw_last_name, sc.raw_first_name) AS names
        ) n
        WHERE {condition}
    """)


_LATEX_CANDIDATES_SQL = candidates_sql("strpos(n.names, chr(92)) > 0")

_UPSERT_CONTRIBUTOR_INFORMATION_SQL = text(f"""
    INSERT INTO contributor_information ({", ".join(CONTRIBUTOR_INFORMATION_KEY_COLUMNS)})
    SELECT DISTINCT t.last_name_normalized, t.first_name_normalized, t.identifiers
    FROM jsonb_to_recordset(:payload) AS t(
        last_name_normalized text, first_name_normalized text, identifiers jsonb)
    ON CONFLICT ({", ".join(CONTRIBUTOR_INFORMATION_KEY_COLUMNS)}) DO NOTHING
""").bindparams(bindparam("payload", type_=Jsonb))

_UPDATE_SOURCE_CONTRIBUTIONS_SQL = text(
    """
    UPDATE source_contributions sc
    SET raw_author_name = t.raw_author_name, raw_last_name = t.raw_last_name,
        raw_first_name = t.raw_first_name, contributor_information_id = ci.id,
        person_id = CASE WHEN ca.source_contribution_id IS NULL THEN NULL ELSE sc.person_id END,
        resolution_mode = CASE WHEN ca.source_contribution_id IS NULL THEN NULL ELSE sc.resolution_mode END
    FROM jsonb_to_recordset(:payload) AS t(
        id integer, raw_author_name text, raw_last_name text, raw_first_name text,
        last_name_normalized text, first_name_normalized text, identifiers jsonb)
    JOIN contributor_information ci ON ci.key_hash = """
    + key_hash_sql([f"t.{c}" for c in CONTRIBUTOR_INFORMATION_KEY_COLUMNS])
    + """
    LEFT JOIN confirmed_source_contributions ca ON ca.source_contribution_id = t.id
    WHERE sc.id = t.id
"""
).bindparams(bindparam("payload", type_=Jsonb))

_MARK_DIRTY_SQL = text("""
    UPDATE publications p SET contributions_dirty = true
    FROM source_records sr
    WHERE sr.id = ANY(:source_records) AND p.id = sr.publication_id AND NOT p.contributions_dirty
""")


def decoded_names(
    conn: Connection,
    candidates: TextClause = _LATEX_CANDIDATES_SQL,
    params: Mapping[str, object] | None = None,
) -> tuple[list[dict[str, object]], list[int]]:
    """Signatures `candidates` dont le nom nettoyé diffère du nom stocké, avec leurs nouvelles colonnes de nom, et leurs notices."""
    rows: list[dict[str, object]] = []
    source_records: set[int] = set()
    for r in conn.execute(candidates, params or {}):
        name = (
            ContributorName.from_parts(r.raw_last_name, r.raw_first_name)
            if r.raw_last_name is not None
            else ContributorName.from_raw(r.raw_author_name)
        )
        if name is None:
            continue
        fields = contributor_name_fields(name)
        if (fields["raw_author_name"], fields["raw_last_name"], fields["raw_first_name"]) == (
            r.raw_author_name,
            r.raw_last_name,
            r.raw_first_name,
        ):
            continue
        rows.append({"id": r.id, **fields, "identifiers": r.identifiers})
        source_records.add(r.source_record)
    return rows, sorted(source_records)


def decode(conn: Connection, rows: list[dict[str, object]], source_records: list[int]) -> int:
    """Écrit les noms décodés et leurs identités, détache les personnes, met à jour les notices et les publications. Rend le nombre d'identités orphelines supprimées."""
    conn.execute(_UPSERT_CONTRIBUTOR_INFORMATION_SQL, {"payload": rows})
    conn.execute(_UPDATE_SOURCE_CONTRIBUTIONS_SQL, {"payload": rows})
    backfill_source_records(conn, source_records)
    conn.execute(_MARK_DIRTY_SQL, {"source_records": source_records})
    return delete_orphan_contributor_information(conn)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        rows, source_records = decoded_names(conn)
        log.info("signatures à décoder : %d, dans %d notices", len(rows), len(source_records))
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
        orphans = decode(conn, rows, source_records)
        conn.commit()
        log.info(
            "signatures décodées : %d ; identités orphelines supprimées : %d", len(rows), orphans
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
