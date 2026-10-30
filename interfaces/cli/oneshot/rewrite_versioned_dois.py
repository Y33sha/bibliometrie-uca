# STATUS: oneshot (2026-10-30)
"""Écrit, depuis le raw store, les DOI des enregistrements sources avec leur suffixe de version (`.v1`, `/v2`).

Chez Crossref et DataCite, l'identifiant que la source donne au payload devient le `source_id` de l'enregistrement source, de sa ligne de `staging` et de sa clé au raw store. Quand un enregistrement source a déjà cet identifiant, l'enregistrement source tronqué est un doublon : sa ligne de `staging` est marquée disparue, et la normalisation le supprime. Quand seule une ligne de `staging` a cet identifiant, l'enregistrement source y est rattaché, et son ancienne ligne de `staging` est supprimée. Dans toutes les sources, l'enregistrement source reçoit les identifiants DOI que la normalisation tire du payload : un DOI inchangé garde son statut, un DOI écrit est actif. Les enregistrements sources modifiés sont marqués pour la réconciliation.

Usage :
    python -m interfaces.cli.oneshot.rewrite_versioned_dois [--sources crossref,datacite] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, Row, text

from domain.source_records.identifiers import SourceIdentifierType
from domain.sources.registry import SOURCE_PRIORITY, Source
from domain.types import JsonValue
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store import UnreadablePayloadError, get_raw_store
from infrastructure.raw_store.base import RawStore
from pipeline.ingestion.common.adapter import RecordIdentity
from pipeline.ingestion.common.normalize import normalizer_builders
from pipeline.ingestion.common.normalizer import SourceNormalizer
from pipeline.ingestion.common.source_records import normalized_identifiers
from pipeline.ingestion.common.staging import StagingRow
from pipeline.ingestion.crossref import ADAPTER as CROSSREF
from pipeline.ingestion.datacite import ADAPTER as DATACITE
from pipeline.transformation.publishing.find_or_create import Containers

log = setup_logger("rewrite_versioned_dois", os.path.dirname(__file__))

_BATCH = 1000

# Sources dont l'identifiant est le DOI, et la fonction qui le tire du payload.
_IDENTIFY: dict[str, Callable[[Mapping[str, JsonValue]], RecordIdentity | None]] = {
    Source.CROSSREF.value: CROSSREF.identify,
    Source.DATACITE.value: DATACITE.identify,
}

# DOI à suffixe de version dans le texte d'un payload : le suffixe termine le DOI.
_VERSIONED_DOI = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+[./]v\d{1,3}(?=[\s\"'<>]|$)", re.IGNORECASE)

_BATCH_ROWS = text("""
    SELECT sr.id, sr.source_id, st.id AS staging_id, st.doi,
           COALESCE((
               SELECT jsonb_agg(jsonb_build_object('value', i.id_value, 'role', i.role,
                                                   'removed_by', i.removed_by))
               FROM source_record_identifiers i
               WHERE i.source_record_id = sr.id AND i.id_type = 'doi'
           ), '[]'::jsonb) AS dois
    FROM source_records sr
    JOIN staging st ON st.id = sr.staging_id
    WHERE sr.source = :source AND sr.id > :after
    ORDER BY sr.id
    LIMIT :limit
""")

_RECORD_EXISTS = text(
    "SELECT EXISTS (SELECT 1 FROM source_records WHERE source = :source AND source_id = :source_id)"
)
_STAGING_ID = text("SELECT id FROM staging WHERE source = :source AND source_id = :source_id")
_MARK_DISAPPEARED = text(
    "UPDATE staging SET disappeared_at = now() WHERE source = :source AND source_id = :source_id"
)

_RENAME = (
    text("UPDATE source_records SET source_id = :new WHERE source = :source AND source_id = :old"),
    text("UPDATE staging SET source_id = :new WHERE source = :source AND source_id = :old"),
)
_RELINK = text(
    "UPDATE source_records SET source_id = :new, staging_id = :staging_id WHERE id = :id"
)
_DELETE_STAGING = text("DELETE FROM staging WHERE source = :source AND source_id = :old")

_DELETE_DOIS = text("""
    DELETE FROM source_record_identifiers
    WHERE source_record_id = ANY(:ids) AND id_type = 'doi'
""")

_INSERT_DOIS = text("""
    INSERT INTO source_record_identifiers (source_record_id, id_type, id_value, role, removed_by)
    SELECT i.source_record_id, 'doi', i.id_value, CAST(i.role AS source_identifier_role),
           i.removed_by
    FROM jsonb_to_recordset(CAST(:identifiers AS jsonb))
        AS i(source_record_id integer, id_value text, role text, removed_by text)
""")


@dataclass
class _Rewriter:
    """Réécriture des enregistrements sources d'une source, lot par lot, avec ses compteurs."""

    conn: Connection
    source: str
    dry_run: bool
    normalizer: SourceNormalizer
    store: RawStore
    identify: Callable[[Mapping[str, JsonValue]], RecordIdentity | None] | None
    counts: Counter[str] = field(default_factory=Counter)

    def batch(self, rows: Sequence[Row[Any]]) -> None:
        """Réécrit un lot, puis le commite."""
        new_dois: list[dict[str, Any]] = []
        changed: set[int] = set()
        for r in rows:
            self._record(r, new_dois, changed)
        if self.dry_run:
            return
        rewritten = sorted({d["source_record_id"] for d in new_dois})
        if rewritten:
            self.conn.execute(_DELETE_DOIS, {"ids": rewritten})
            self.conn.execute(_INSERT_DOIS, {"identifiers": json.dumps(new_dois)})
        if changed:
            enqueue(
                self.conn,
                Queue.SOURCE_RECORD_KEYS,
                "SELECT unnest(CAST(:ids AS integer[]))",
                {"ids": sorted(changed)},
            )
        self.conn.commit()

    def _record(self, r: Row[Any], new_dois: list[dict[str, Any]], changed: set[int]) -> None:
        try:
            payload = self.store.get(self.source, r.source_id)
        except KeyError, UnreadablePayloadError:
            self.counts["sans payload au raw store"] += 1
            return
        raw_text = payload.decode()
        if self.identify is None and not _VERSIONED_DOI.search(raw_text):
            return
        raw_data = json.loads(raw_text)
        identity = self.identify(raw_data) if self.identify is not None else None
        source_id = identity.source_id if identity is not None else r.source_id
        if source_id != r.source_id and self._duplicate(r.source_id, source_id):
            return
        row = StagingRow(id=r.staging_id, source_id=source_id, doi=r.doi, raw_data=raw_data)
        doc = self.normalizer.parse(row)
        if doc is None:
            return
        record = self.normalizer.source_record(row, doc, Containers(None, None))
        dois = [i for i in normalized_identifiers(record) if i.id_type is SourceIdentifierType.DOI]
        if {(i.value, i.role.value) for i in dois} != {(d["value"], d["role"]) for d in r.dois}:
            self.counts["jeux de DOI réécrits"] += 1
            changed.add(r.id)
            statuses = {d["value"]: d["removed_by"] for d in r.dois}
            new_dois.extend(
                {
                    "source_record_id": r.id,
                    "id_value": i.value,
                    "role": i.role.value,
                    "removed_by": statuses.get(i.value),
                }
                for i in dois
            )
        if source_id != r.source_id:
            changed.add(r.id)
            self._rename(r.id, r.source_id, source_id, payload)

    def _duplicate(self, old: str, new: str) -> bool:
        """Vrai si un enregistrement source a déjà l'identifiant `new` : la ligne de staging de `old` est marquée disparue, et la normalisation supprime ce doublon."""
        if not self.conn.execute(
            _RECORD_EXISTS, {"source": self.source, "source_id": new}
        ).scalar():
            return False
        self.counts["doublons marqués disparus"] += 1
        log.info("%s : %s, doublon de %s", self.source, old, new)
        if not self.dry_run:
            self.conn.execute(_MARK_DISAPPEARED, {"source": self.source, "source_id": old})
        return True

    def _rename(self, record_id: int, old: str, new: str, payload: bytes) -> None:
        """Donne l'identifiant `new` à l'enregistrement source. Une ligne de staging qui a déjà cet identifiant, celle de la version, devient la sienne."""
        self.counts["identifiants réécrits"] += 1
        names = {"source": self.source, "old": old, "new": new}
        staged_id = self.conn.execute(
            _STAGING_ID, {"source": self.source, "source_id": new}
        ).scalar()
        if staged_id is not None:
            self.counts["rattachés à la ligne de staging de la version"] += 1
        if self.dry_run:
            return
        if staged_id is not None:
            self.conn.execute(_RELINK, {"id": record_id, "new": new, "staging_id": staged_id})
            self.conn.execute(_DELETE_STAGING, names)
        else:
            for statement in _RENAME:
                self.conn.execute(statement, names)
            self.store.put(self.source, new, payload)
        self.store.delete(self.source, old)


def _rewrite_source(conn: Connection, source: str, *, dry_run: bool) -> None:
    rewriter = _Rewriter(
        conn,
        source,
        dry_run,
        normalizer_builders(archive=False)[source](conn, log),
        get_raw_store(),
        _IDENTIFY.get(source),
    )
    after = seen = 0
    while rows := conn.execute(
        _BATCH_ROWS, {"source": source, "after": after, "limit": _BATCH}
    ).all():
        after = rows[-1].id
        seen += len(rows)
        rewriter.batch(rows)
        log.info("%s : %d traités", source, seen)
    log.info("%s : %s", source, dict(rewriter.counts))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources", help="Sources à traiter, séparées par des virgules. Toutes par défaut."
    )
    parser.add_argument("--dry-run", action="store_true", help="Compte sans rien écrire")
    args = parser.parse_args()
    sources = args.sources.split(",") if args.sources else [s.value for s in SOURCE_PRIORITY]
    with get_sync_engine().connect() as conn:
        for source in sources:
            _rewrite_source(conn, source, dry_run=args.dry_run)
        if args.dry_run:
            log.info("Dry-run, rien écrit.")


if __name__ == "__main__":
    main()
