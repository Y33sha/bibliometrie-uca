# STATUS: oneshot (2026-10-21)
"""Remplit `raw_doc_type` et `raw_language` de `source_records`, et met `raw_metadata` dans la forme où il garde seulement les corrections par une règle.

Pour chaque enregistrement source dont `raw_doc_type` est vide :

- `raw_doc_type` reçoit le type de la source : la valeur gardée dans `raw_metadata`, sinon `doc_type` ;
- une entrée `doc_type` de `raw_metadata` posée par la traduction (`DOC_TYPE_MAP`) disparaît, et `doc_type` reçoit la traduction du type de la source ;
- une entrée `doc_type` posée par une règle garde la règle et reçoit la traduction du type de la source.

Pour chaque enregistrement source dont `raw_language` est vide, `raw_language` reçoit la langue de la source, l'entrée `language` de `raw_metadata` disparaît, et `language` reçoit le code de la langue.

Un enregistrement source dont `doc_type` change est marqué `keys_dirty`.

Usage :
    python -m interfaces.cli.oneshot.split_raw_doc_type_language [--dry-run]
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import cast

from sqlalchemy import Connection, bindparam, text

from domain.source_records.doc_types import map_doc_type
from domain.source_records.languages import language_code
from domain.source_records.raw_metadata import CORRECTED_BY, RAW, stash_entry
from domain.types import JsonValue
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.jsonb import Jsonb
from infrastructure.observability.log import setup_logger
from pipeline.ingestion.common.source_records import fetch_language_forms

log = setup_logger("split_raw_doc_type_language", os.path.dirname(__file__))

_DOC_TYPE_MAP_MARKER = "DOC_TYPE_MAP"


@dataclass(frozen=True)
class Row:
    id: int
    source: str
    doc_type: str | None
    language: str | None
    raw_doc_type: str | None
    raw_language: str | None
    doc_type_entry: dict[str, JsonValue] | None
    language_entry: dict[str, JsonValue] | None


@dataclass(frozen=True)
class Update:
    id: int
    doc_type: str | None
    raw_doc_type: str | None
    language: str | None
    raw_language: str | None
    doc_type_entry: dict[str, JsonValue] | None
    """Entrée `doc_type` de `raw_metadata` ; `None` la retire."""
    keys_dirty: bool


def _translated(raw: str | None, source: str) -> str | None:
    return None if raw is None else map_doc_type(raw, source)


def plan_row(row: Row, forms: Mapping[str, str]) -> Update | None:
    """Mise à jour d'un enregistrement source, `None` quand il est déjà dans la forme cible."""
    if row.raw_doc_type is not None and row.raw_language is not None:
        return None
    doc_type, raw_doc_type, doc_type_entry = row.doc_type, row.raw_doc_type, row.doc_type_entry
    if row.raw_doc_type is None:
        entry = row.doc_type_entry
        raw_doc_type = cast("str | None", entry[RAW]) if entry and RAW in entry else row.doc_type
        translated = _translated(raw_doc_type, row.source)
        rule = entry.get(CORRECTED_BY) if entry else None
        if isinstance(rule, str) and rule != _DOC_TYPE_MAP_MARKER:
            doc_type_entry = stash_entry(translated, rule)
        else:
            doc_type, doc_type_entry = translated, None
    language, raw_language = row.language, row.raw_language
    if row.raw_language is None:
        entry = row.language_entry
        raw_language = cast("str | None", entry[RAW]) if entry and RAW in entry else row.language
        language = language_code(raw_language, forms)
    unchanged = (doc_type, raw_doc_type, language, raw_language, doc_type_entry) == (
        row.doc_type,
        row.raw_doc_type,
        row.language,
        row.raw_language,
        row.doc_type_entry,
    )
    if unchanged and row.language_entry is None:
        return None
    return Update(
        row.id,
        doc_type,
        raw_doc_type,
        language,
        raw_language,
        doc_type_entry,
        keys_dirty=doc_type != row.doc_type,
    )


def plan(rows: Iterable[Row], forms: Mapping[str, str]) -> list[Update]:
    return [u for row in rows if (u := plan_row(row, forms)) is not None]


def fetch_rows(conn: Connection) -> list[Row]:
    return [
        Row(*r)
        for r in conn.execute(
            text("""
                SELECT id, source::text, doc_type, language, raw_doc_type, raw_language,
                       raw_metadata -> 'doc_type', raw_metadata -> 'language'
                FROM source_records
                WHERE raw_doc_type IS NULL OR raw_language IS NULL
            """)
        )
    ]


def apply(conn: Connection, updates: list[Update]) -> int:
    """Écrit les mises à jour. Rend le nombre d'enregistrements sources modifiés."""
    if not updates:
        return 0
    return conn.execute(
        text("""
            UPDATE source_records sr
            SET doc_type = t.doc_type,
                raw_doc_type = t.raw_doc_type,
                language = t.language,
                raw_language = t.raw_language,
                raw_metadata = CASE
                    WHEN t.doc_type_entry IS NULL THEN sr.raw_metadata - 'doc_type' - 'language'
                    ELSE (sr.raw_metadata - 'language')
                         || jsonb_build_object('doc_type', t.doc_type_entry)
                END,
                keys_dirty = sr.keys_dirty OR t.keys_dirty,
                updated_at = clock_timestamp()
            FROM jsonb_to_recordset(:payload) AS t(
                id integer, doc_type text, raw_doc_type text, language text,
                raw_language text, doc_type_entry jsonb, keys_dirty boolean)
            WHERE sr.id = t.id
        """).bindparams(bindparam("payload", type_=Jsonb)),
        {"payload": [u.__dict__ for u in updates]},
    ).rowcount


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        updates = plan(fetch_rows(conn), fetch_language_forms(conn))
        log.info(
            "enregistrements sources à mettre à jour : %d, dont %d à doc_type modifié",
            len(updates),
            sum(u.keys_dirty for u in updates),
        )
        if args.dry_run:
            conn.rollback()
            return 0
        written = apply(conn, updates)
        conn.commit()
        log.info("enregistrements sources mis à jour : %d", written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
