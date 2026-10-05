# STATUS: oneshot (2026-10-05)
"""Rattache les signatures existantes à leur identité découpée en nom et prénom.

La synchronisation des signatures d'une notice renormalisée rapproche les signatures par identité : nom, prénom et identifiants normalisés. Les signatures écrites avant le découpage portent une identité sans nom ni prénom. Sans ce script, la renormalisation les supprimerait puis les recréerait, en perdant leur personne et leur épinglage.

Pour chaque signature, le script écrit le nom tel que la source le donne et rattache la signature à l'identité de son découpage :

- Crossref, DataCite, WoS, HAL et theses.fr : nom et prénom relus dans le payload du raw store, par les fonctions de parsing des normaliseurs. Une signature est rapprochée de l'auteur du payload qui porte les mêmes mots, à la même position de préférence.
- OpenAlex, ScanR, et signatures sans auteur correspondant dans le payload : chaîne stockée, découpée par le parseur.

Les identités devenues orphelines sont purgées en fin de script. Idempotent.

Usage :
    python -m interfaces.cli.oneshot.backfill_signature_names                   # exécution
    python -m interfaces.cli.oneshot.backfill_signature_names --dry-run         # rapport seul
    python -m interfaces.cli.oneshot.backfill_signature_names --source hal      # une source
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from functools import lru_cache
from typing import NamedTuple

from sqlalchemy import Connection, bindparam, text

from application.pipeline.normalize._authorships_batch import signature_name_fields
from application.pipeline.normalize.normalize_crossref import build_crossref_author_records
from application.pipeline.normalize.normalize_datacite import build_datacite_author_records
from application.pipeline.normalize.normalize_hal import (
    build_hal_author_records,
    extract_hal_author_block,
)
from application.pipeline.normalize.normalize_wos import (
    build_wos_author_records,
    extract_from_api,
    extract_wos_author_block,
)
from application.pipeline.progression import JALON_INTERVALLE_S
from application.ports.pipeline.normalize.authorships import SignatureNameFields
from domain.normalize import clean_raw_author_name, normalize_name_form
from domain.persons.signature_name import SignatureName
from domain.sources.theses import aggregate_thesis_persons
from domain.types import JsonValue, as_mapping
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.jsonb import Jsonb
from infrastructure.observability.log import setup_logger
from infrastructure.pipeline.normalize.authorships import (
    IDENTITY_KEY_COLUMNS,
    delete_orphan_identities,
    key_hash_sql,
)
from infrastructure.raw_store.base import RawStore, UnreadablePayloadError
from infrastructure.raw_store.factory import get_raw_store

log = setup_logger("backfill_signature_names", os.path.dirname(__file__))

_SOURCES = ("crossref", "datacite", "wos", "hal", "theses", "openalex", "scanr")
# Lignes lues par aller-retour du flux, et signatures écrites par paquet.
_STREAM_ROWS = 20_000
_WRITE_ROWS = 20_000
# Noms distincts gardés en cache.
_NAME_CACHE = 2_000_000

_PayloadNames = Callable[
    [Mapping[str, JsonValue], str | None], list[tuple[int | None, SignatureName]]
]

# Auteurs (position, nom) d'un payload du raw store, par les fonctions de parsing des normaliseurs.
_PAYLOAD_NAMES: dict[str, _PayloadNames] = {
    "crossref": lambda p, _doi: [(r.position, r.name) for r in build_crossref_author_records(p)],
    "datacite": lambda p, _doi: [
        (r.position, r.name) for r in build_datacite_author_records(as_mapping(p.get("attributes")))
    ],
    "hal": lambda p, _doi: [
        (r.position, r.name) for r in build_hal_author_records(extract_hal_author_block(p))
    ],
    "wos": lambda p, doi: [
        (r.position, r.name)
        for r in build_wos_author_records(extract_wos_author_block(extract_from_api(p, doi)), log)
    ],
    "theses": lambda p, _doi: [(a.author_position, a.name) for a in aggregate_thesis_persons(p)],
}


# Auteurs d'un payload, (position, nom) indexés par les mots de leur nom.
_PayloadAuthors = dict[frozenset[str], list[tuple[int | None, SignatureName]]]


class _Notice(NamedTuple):
    id: int
    source_id: str
    doi: str | None


class _RepointItem(SignatureNameFields):
    sa_id: int
    person_identifiers: JsonValue


class _StoredSignature(NamedTuple):
    id: int
    source_publication_id: int
    source_id: str
    doi: str | None
    author_position: int | None
    raw_author_name: str | None
    raw_last_name: str | None
    raw_first_name: str | None
    person_identifiers: JsonValue


@lru_cache(maxsize=_NAME_CACHE)
def _name_fields(name: SignatureName) -> SignatureNameFields:
    """`signature_name_fields`, mis en cache : un même nom revient d'une notice à l'autre."""
    return signature_name_fields(name)


@lru_cache(maxsize=_NAME_CACHE)
def _words(name: SignatureName) -> frozenset[str]:
    return frozenset(normalize_name_form(clean_raw_author_name(name.display())).split())


def _stored_name(row: _StoredSignature) -> SignatureName:
    """Nom stocké d'une signature : nom et prénom de la source s'ils sont déjà écrits, sinon la chaîne brute."""
    if row.raw_last_name is not None:
        return SignatureName(last_name=row.raw_last_name, first_name=row.raw_first_name)
    return SignatureName(raw=row.raw_author_name)


def _match(
    stored: SignatureName, position: int | None, authors: _PayloadAuthors
) -> SignatureName | None:
    """Auteur du payload aux mêmes mots que la signature : celui de même position, sinon le seul à porter ces mots."""
    same = authors.get(_words(stored), [])
    at_position = [name for pos, name in same if pos == position]
    if at_position:
        return at_position[0]
    return same[0][1] if len(same) == 1 else None


def _notices(conn: Connection, source: str) -> Iterator[tuple[_Notice, list[_StoredSignature]]]:
    """Signatures de la source, notice par notice, lues en un seul flux trié par notice."""
    rows = conn.execute(
        text("""
            SELECT sa.id, sa.source_publication_id, sp.source_id, sp.doi, sa.author_position,
                   sa.raw_author_name, sa.raw_last_name, sa.raw_first_name, aik.person_identifiers
            FROM source_authorships sa
            JOIN source_publications sp ON sp.id = sa.source_publication_id
            JOIN author_identifying_keys aik ON aik.id = sa.identity_id
            WHERE sa.source = :source
            ORDER BY sa.source_publication_id
        """),
        {"source": source},
        execution_options={"stream_results": True, "yield_per": _STREAM_ROWS},
    )
    signatures: list[_StoredSignature] = []
    for row in rows:
        signature = _StoredSignature(*row)
        if signatures and signature.source_publication_id != signatures[0].source_publication_id:
            yield _notice_of(signatures[0]), signatures
            signatures = []
        signatures.append(signature)
    if signatures:
        yield _notice_of(signatures[0]), signatures


def _notice_of(signature: _StoredSignature) -> _Notice:
    return _Notice(signature.source_publication_id, signature.source_id, signature.doi)


def _payload_authors(
    raw_store: RawStore, source: str, notice: _Notice, stats: Counter[str]
) -> _PayloadAuthors:
    authors: _PayloadAuthors = {}
    payload_names = _PAYLOAD_NAMES.get(source)
    if payload_names is None:
        return authors
    try:
        payload = json.loads(raw_store.get(source, notice.source_id))
    except KeyError:
        stats["notices sans payload"] += 1
        return authors
    except UnreadablePayloadError:
        stats["notices au payload illisible"] += 1
        return authors
    for position, name in payload_names(payload, notice.doi):
        authors.setdefault(_words(name), []).append((position, name))
    return authors


_UPSERT_IDENTITIES_SQL = text(f"""
    INSERT INTO author_identifying_keys ({", ".join(IDENTITY_KEY_COLUMNS)})
    SELECT DISTINCT t.author_name_normalized, t.last_name_normalized, t.first_name_normalized,
           t.person_identifiers
    FROM jsonb_to_recordset(:payload) AS t(
        author_name_normalized text, last_name_normalized text, first_name_normalized text,
        person_identifiers jsonb)
    ON CONFLICT ({", ".join(IDENTITY_KEY_COLUMNS)}) DO NOTHING
""").bindparams(bindparam("payload", type_=Jsonb))

_REPOINT_SQL = text(
    """
    UPDATE source_authorships sa
    SET raw_author_name = t.raw_author_name,
        raw_last_name = t.raw_last_name,
        raw_first_name = t.raw_first_name,
        identity_id = aik.id
    FROM jsonb_to_recordset(:payload) AS t(
        sa_id integer, raw_author_name text, raw_last_name text, raw_first_name text,
        author_name_normalized text, last_name_normalized text, first_name_normalized text,
        person_identifiers jsonb)
    JOIN author_identifying_keys aik ON aik.key_hash = """
    + key_hash_sql([f"t.{c}" for c in IDENTITY_KEY_COLUMNS])
    + """
    WHERE sa.id = t.sa_id
"""
).bindparams(bindparam("payload", type_=Jsonb))


def _write(conn: Connection, items: list[_RepointItem]) -> None:
    conn.execute(_UPSERT_IDENTITIES_SQL, {"payload": items})
    conn.execute(_REPOINT_SQL, {"payload": items})


def backfill_source(
    read_conn: Connection,
    write_conn: Connection,
    raw_store: RawStore,
    source: str,
    *,
    apply: bool,
    commit: Callable[[], None],
) -> Counter[str]:
    """Rattache les signatures d'une source à leur identité découpée. Retourne les comptes.

    `read_conn` porte le flux de lecture des signatures, `write_conn` les écritures. `commit` valide chaque paquet écrit.
    """
    stats: Counter[str] = Counter()
    total: int = read_conn.execute(
        text("SELECT count(*) FROM source_publications WHERE source = :source"),
        {"source": source},
    ).scalar_one()
    log.info("%s : %d notices", source, total)
    next_milestone = time.monotonic() + JALON_INTERVALLE_S
    pending: list[_RepointItem] = []
    for notice, signatures in _notices(read_conn, source):
        if time.monotonic() >= next_milestone:
            next_milestone = time.monotonic() + JALON_INTERVALLE_S
            log.info(
                "%s : %d notices sur %d, %d signatures",
                source,
                stats["notices"],
                total,
                stats["signatures"],
            )
        stats["notices"] += 1
        authors = _payload_authors(raw_store, source, notice, stats)
        for s in signatures:
            stored = _stored_name(s)
            name = _match(stored, s.author_position, authors)
            stats["signatures"] += 1
            stats["nom de la source relu" if name is not None else "chaîne stockée découpée"] += 1
            pending.append(
                {
                    "sa_id": s.id,
                    **_name_fields(name if name is not None else stored),
                    "person_identifiers": s.person_identifiers,
                }
            )
        if apply and len(pending) >= _WRITE_ROWS:
            _write(write_conn, pending)
            commit()
            pending = []
    if apply and pending:
        _write(write_conn, pending)
        commit()
    log.info("%s : %s", source, dict(stats))
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    parser.add_argument("--source", choices=_SOURCES, help="Une seule source (défaut : toutes).")
    args = parser.parse_args()
    apply = not args.dry_run
    if not apply:
        log.info("DRY-RUN (rapport seul) — retirer --dry-run pour écrire")

    engine = get_sync_engine()
    raw_store = get_raw_store()
    with engine.connect() as read_conn, engine.connect() as write_conn:
        for source in [args.source] if args.source else _SOURCES:
            backfill_source(
                read_conn, write_conn, raw_store, source, apply=apply, commit=write_conn.commit
            )
            read_conn.rollback()
        if apply:
            log.info("identités orphelines purgées : %d", delete_orphan_identities(write_conn))
            write_conn.commit()
            log.info("✓ backfill appliqué")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
