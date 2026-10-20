# STATUS: oneshot (2026-10-16)
"""Recalcule les formes normalisées stockées avec `normalize_text`, qui conserve les écritures non latines.

Le script recalcule chaque valeur avec la fonction du pipeline et écrit celles qui diffèrent :

- colonnes calculées d'une autre colonne de la même ligne : titres, noms d'éditeurs et de préfixes DOI, noms des personnes, adresses, libellés de sujets. Toutes les lignes sont relues : une forme calculée d'un texte depuis assaini (`&amp;` devenu `&`) est périmée, même en ASCII ;
- formes de noms des revues et des éditeurs : la forme recalculée d'un titre ou d'un nom non ASCII s'ajoute aux formes existantes, les formes vides sont supprimées ;
- identités d'auteur : chaque signature dont le nom contient un caractère non ASCII est rattachée à l'identité de son nom recalculé, puis les identités orphelines sont purgées.

La phase `persons` suivante resynchronise les formes de noms des personnes. Idempotent.

Usage :
    python -m interfaces.cli.oneshot.recompute_normalized_texts            # exécution
    python -m interfaces.cli.oneshot.recompute_normalized_texts --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection, bindparam, text

from domain.normalize import normalize_name, normalize_text, to_plain_text
from domain.persons.signature_name import SignatureName
from domain.publications.metadata import normalized_title
from domain.publishers.names import publisher_name_key
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.jsonb import Jsonb
from infrastructure.observability.log import setup_logger
from pipeline.ingestion.common.signature_queries import (
    IDENTITY_KEY_COLUMNS,
    delete_orphan_identities,
    key_hash_sql,
)
from pipeline.ingestion.common.signatures import signature_name_fields
from pipeline.transformation.publishing.journals.journals import JournalGatewayQueries
from pipeline.transformation.publishing.publishers.store import PublisherStore

log = setup_logger("recompute_normalized_texts", os.path.dirname(__file__))

_NON_ASCII = "[^\x01-\x7f]"
_EXAMPLES = 3
_STREAM = 10_000


def _plain_normalized(value: str) -> str | None:
    return normalize_text(to_plain_text(value)) or None


@dataclass(frozen=True)
class _Column:
    """Colonne normalisée `target`, calculée par `compute` depuis la colonne `source` de la même ligne."""

    table: str
    key: str
    source: str
    target: str
    compute: Callable[[str], str | None]


_COLUMNS = (
    _Column("source_publications", "id", "title", "title_normalized", normalized_title),
    _Column("publications", "id", "title", "title_normalized", normalize_text),
    _Column("journals", "id", "title", "title_normalized", normalize_text),
    _Column(
        "monographs", "id", "title", "title_normalized", lambda t: normalize_text(to_plain_text(t))
    ),
    _Column(
        "publishers", "id", "name", "name_normalized", lambda n: normalize_text(to_plain_text(n))
    ),
    _Column(
        "doi_prefixes",
        "prefix",
        "publisher_name_raw",
        "publisher_name_normalized",
        _plain_normalized,
    ),
    _Column(
        "doi_prefixes", "prefix", "client_name_raw", "client_name_normalized", _plain_normalized
    ),
    _Column("persons", "id", "last_name", "last_name_normalized", normalize_name),
    _Column("persons", "id", "first_name", "first_name_normalized", normalize_name),
    _Column("addresses", "id", "raw_text", "normalized_text", normalize_text),
    _Column("subjects", "id", "label", "label_normalized", normalize_text),
)


def _recompute_column(conn: Connection, column: _Column, *, apply: bool) -> int:
    """Écrit les valeurs de `column` qui changent. Retourne leur nombre."""
    rows = conn.execute(
        text(
            f"SELECT {column.key} AS key, {column.source} AS source, {column.target} AS target"
            f" FROM {column.table} WHERE {column.source} IS NOT NULL"
        )
    ).all()
    payload = [
        {"key": r.key, "value": value}
        for r in rows
        if (value := column.compute(r.source)) != r.target
    ]
    for item in payload[:_EXAMPLES]:
        source = next(r.source for r in rows if r.key == item["key"])
        log.info("    · %r → %r", source[:80], (item["value"] or "")[:80])
    if apply and payload:
        key_type = "text" if column.key == "prefix" else "int"
        conn.execute(
            text(
                f"UPDATE {column.table} t SET {column.target} = p.value"
                f" FROM jsonb_to_recordset(:payload) AS p(key {key_type}, value text)"
                f" WHERE t.{column.key} = p.key"
            ).bindparams(bindparam("payload", type_=Jsonb)),
            {"payload": payload},
        )
    return len(payload)


def _add_name_forms(conn: Connection, *, apply: bool) -> tuple[int, int, int]:
    """Supprime les formes de noms de revues vides, ajoute les formes recalculées des titres de revues et des noms d'éditeurs. Retourne (formes vides, formes de revues, formes d'éditeurs) candidates."""
    empty = conn.execute(
        text("SELECT count(*) FROM journal_name_forms WHERE form_normalized = ''")
    ).scalar_one()
    journals = [
        (r.id, form, r.publisher_id)
        for r in conn.execute(
            text("SELECT id, title, publisher_id FROM journals WHERE title ~ :pattern"),
            {"pattern": _NON_ASCII},
        )
        if (form := normalize_text(r.title))
    ]
    publishers = [
        (r.id, key)
        for r in conn.execute(
            text("SELECT id, name FROM publishers WHERE name ~ :pattern"), {"pattern": _NON_ASCII}
        )
        if (key := publisher_name_key(to_plain_text(r.name)))
    ]
    if apply:
        conn.execute(text("DELETE FROM journal_name_forms WHERE form_normalized = ''"))
        journal_gateway = JournalGatewayQueries(conn)
        for journal_id, form, publisher_id in journals:
            journal_gateway.add_journal_name_form(journal_id, form, publisher_id)
        publisher_store = PublisherStore(conn)
        for publisher_id, key in publishers:
            publisher_store.add_publisher_name_form(publisher_id, key)
    return empty, len(journals), len(publishers)


_SIGNATURES_SQL = text("""
    SELECT sa.id, sa.raw_author_name, sa.raw_last_name, sa.raw_first_name,
           aik.last_name_normalized, aik.first_name_normalized, aik.person_identifiers
    FROM source_authorships sa
    JOIN author_identifying_keys aik ON aik.id = sa.identity_id
    WHERE sa.raw_author_name ~ :pattern OR sa.raw_last_name ~ :pattern
       OR sa.raw_first_name ~ :pattern
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


def _repoint_signatures(conn: Connection, *, apply: bool) -> int:
    """Rattache chaque signature dont le nom normalisé change à l'identité de ce nom. Retourne leur nombre."""
    payload = []
    # Curseur serveur pour cette seule lecture : posé sur la connexion, il s'étendrait aux écritures qui suivent.
    result = conn.execute(
        _SIGNATURES_SQL.execution_options(yield_per=_STREAM), {"pattern": _NON_ASCII}
    )
    for row in result:
        name = SignatureName.from_columns(
            row.raw_author_name, row.raw_last_name, row.raw_first_name
        )
        fields = signature_name_fields(name)
        split = (fields["last_name_normalized"], fields["first_name_normalized"])
        if split == (row.last_name_normalized, row.first_name_normalized):
            continue
        if len(payload) < _EXAMPLES:
            log.info("    · %r → %r", (row.last_name_normalized, row.first_name_normalized), split)
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
        for column in _COLUMNS:
            log.info("%s.%s…", column.table, column.target)
            log.info("  %d valeurs changées", _recompute_column(conn, column, apply=apply))
        empty, journals, publishers = _add_name_forms(conn, apply=apply)
        log.info(
            "formes de noms : %d formes de revues vides, %d titres de revues et %d noms d'éditeurs non ASCII",
            empty,
            journals,
            publishers,
        )
        log.info("signatures…")
        log.info("  %d signatures changent d'identité", _repoint_signatures(conn, apply=apply))
        if apply:
            log.info("identités orphelines purgées : %d", delete_orphan_identities(conn))
            conn.commit()
            log.info("✓ recalcul appliqué")
        else:
            log.info("DRY-RUN — aucune écriture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
