# STATUS: oneshot (2026-11-02)
"""Met en texte brut les titres de conteneur et les noms d'éditeur stockés, comme la normalisation à leur écriture : entités HTML décodées, balises retirées.

Colonnes réécrites : `source_records.biblio` (éditeur, titre de la revue), `source_records.container_title`, et les noms de `doi_prefixes` avec leurs formes normalisées. Les enregistrements sources modifiés passent en file de réconciliation : la phase `publications` suivante recalcule leurs publications. Idempotent.

Usage :
    uv run python -m interfaces.cli.oneshot.flatten_container_texts            # exécution
    uv run python -m interfaces.cli.oneshot.flatten_container_texts --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping

from sqlalchemy import Connection, bindparam, text

from domain.normalize import normalize_text, optional_plain_text
from domain.serials.titles import names_ebook_platform
from domain.source_records.biblio import BiblioKey, JournalKey
from domain.types import JsonValue
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger

log = setup_logger("flatten_container_texts", os.path.dirname(__file__))

_EXAMPLES = 5
_BATCH = 1_000

_SOURCE_RECORDS = text("""
    SELECT id, biblio, container_title FROM source_records
    WHERE biblio->>'publisher' ~ '[&<]' OR biblio->'journal'->>'title' ~ '[&<]'
       OR container_title ~ '[&<]'
""")

_WRITE_SOURCE_RECORDS = text("""
    UPDATE source_records sr SET biblio = p.biblio, container_title = p.container_title
    FROM jsonb_to_recordset(:payload) AS p(id int, biblio jsonb, container_title text)
    WHERE sr.id = p.id
""").bindparams(bindparam("payload", type_=Jsonb))

_DOI_PREFIXES = text("""
    SELECT prefix, publisher_name_raw, client_name_raw FROM doi_prefixes
    WHERE publisher_name_raw ~ '[&<]' OR client_name_raw ~ '[&<]'
""")

_WRITE_DOI_PREFIX = text("""
    UPDATE doi_prefixes SET publisher_name_raw = :publisher, publisher_name_normalized = :publisher_normalized,
        client_name_raw = :client, client_name_normalized = :client_normalized
    WHERE prefix = :prefix
""")


def _with(mapping: Mapping[str, JsonValue], key: str, value: JsonValue) -> dict[str, JsonValue]:
    """Renvoie `mapping` où `key` vaut `value`, sans `key` si `value` est vide."""
    result = {k: v for k, v in mapping.items() if k != key}
    if value:
        result[key] = value
    return result


def _flattened_biblio(biblio: Mapping[str, JsonValue] | None) -> dict[str, JsonValue] | None:
    """Renvoie `biblio` dont l'éditeur et le titre de la revue sont en texte brut ; `None` sans aucune valeur."""
    if not biblio:
        return None
    result = dict(biblio)
    if isinstance(publisher := result.get(BiblioKey.PUBLISHER), str):
        result = _with(result, BiblioKey.PUBLISHER, optional_plain_text(publisher))
    journal = result.get(BiblioKey.JOURNAL)
    if isinstance(journal, Mapping) and isinstance(title := journal.get(JournalKey.TITLE), str):
        journal = _with(journal, JournalKey.TITLE, optional_plain_text(title))
        result = _with(result, BiblioKey.JOURNAL, journal)
    return result or None


def _flattened_container_title(title: str | None) -> str | None:
    """Renvoie le titre de conteneur en texte brut, `None` pour un titre de plateforme d'ebooks."""
    flat = optional_plain_text(title)
    return None if flat and names_ebook_platform(flat) else flat


def _changed_source_records(conn: Connection) -> list[dict[str, object]]:
    changed: list[dict[str, object]] = []
    for row in conn.execute(_SOURCE_RECORDS):
        biblio = _flattened_biblio(row.biblio)
        container_title = _flattened_container_title(row.container_title)
        if biblio != row.biblio or container_title != row.container_title:
            changed.append(
                {
                    "id": row.id,
                    "biblio": biblio,
                    "container_title": container_title,
                    "before": (row.biblio, row.container_title),
                }
            )
    return changed


def _changed_doi_prefixes(conn: Connection) -> list[dict[str, object]]:
    changed: list[dict[str, object]] = []
    for row in conn.execute(_DOI_PREFIXES):
        publisher = optional_plain_text(row.publisher_name_raw)
        client = optional_plain_text(row.client_name_raw)
        if (publisher, client) == (row.publisher_name_raw, row.client_name_raw):
            continue
        changed.append(
            {
                "prefix": row.prefix,
                "publisher": publisher,
                "publisher_normalized": normalize_text(publisher or "") or None,
                "client": client,
                "client_normalized": normalize_text(client or "") or None,
            }
        )
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="rapport seul, sans écriture")
    args = parser.parse_args()

    with get_sync_engine().begin() as conn:
        records = _changed_source_records(conn)
        prefixes = _changed_doi_prefixes(conn)
        log.info("%d enregistrements sources à réécrire", len(records))
        for c in records[:_EXAMPLES]:
            log.info("    · %r → %r", c["before"], (c["biblio"], c["container_title"]))
        log.info("%d préfixes DOI à réécrire", len(prefixes))
        for p in prefixes[:_EXAMPLES]:
            log.info("    · %s : %r, %r", p["prefix"], p["publisher"], p["client"])
        if args.dry_run:
            return
        payload = [
            {"id": c["id"], "biblio": c["biblio"], "container_title": c["container_title"]}
            for c in records
        ]
        for start in range(0, len(payload), _BATCH):
            conn.execute(_WRITE_SOURCE_RECORDS, {"payload": payload[start : start + _BATCH]})
        for p in prefixes:
            conn.execute(_WRITE_DOI_PREFIX, p)
        ids = [c["id"] for c in records]
        enqueue(conn, Queue.SOURCE_RECORD_KEYS, "SELECT unnest(CAST(:ids AS int[]))", {"ids": ids})
        log.info("%d enregistrements sources en file de réconciliation", len(ids))


if __name__ == "__main__":
    main()
