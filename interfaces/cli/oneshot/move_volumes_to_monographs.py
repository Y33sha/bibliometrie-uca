# STATUS: oneshot (2026-09-21)
"""Conteneurs du stock selon `determine_container_type` : la série dans `journals`, le volume dans `monographs`.

La description du conteneur de chaque enregistrement se reconstruit à partir des champs en base : son entrée de `journals` telle que la normalisation l'a donnée (avant correction par espace de noms DOI), sa monographie, son type brut et ses ISBN. `find_or_create_containers` en tire la série et le volume, comme à la normalisation.

Le script traite les enregistrements absents du raw store, que la renormalisation laisse en l'état. Il écrit leurs conteneurs, retire la trace `raw_metadata.journal_id`, que `metadata_correction` recalcule, et marque l'enregistrement pour la phase `publications`. Enchaîner ensuite `run_pipeline --from publishers_journals`.

`--audit N` compare ce calcul à la normalisation, sur N notices du raw store par strate. Pour chaque notice, dans une transaction annulée ensuite, le calcul sur la base résout d'abord les conteneurs, puis la normalisation rejouée sur la notice brute doit retrouver les mêmes entrées.

Usage :
    python -m interfaces.cli.oneshot.move_volumes_to_monographs [--dry-run]
    python -m interfaces.cli.oneshot.move_volumes_to_monographs --audit 150
"""

from __future__ import annotations

import argparse
import json
import os
import random
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from typing import NamedTuple

from sqlalchemy import Connection, text

from application.pipeline.normalize import (
    normalize_crossref,
    normalize_datacite,
    normalize_hal,
    normalize_openalex,
    normalize_scanr,
    normalize_wos,
)
from application.services.monographs.containers import Containers, find_or_create_containers
from domain.journals.containers import (
    ContainerDescription,
    ContainerRole,
    container_role,
    is_dated_event_without_issn,
)
from domain.journals.issns import IssnSupport, JournalIssn
from domain.journals.journal import OaModel
from domain.normalize import normalize_text
from domain.sources.hal import hal_text_field
from domain.sources.openalex import parse_primary_location, should_skip_publisher_journal
from domain.types import JsonValue, as_mapping, as_sequence, as_str, as_strs
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.pipeline.containers import PgContainerGatewayQueries
from infrastructure.pipeline.publishers import PgPublisherGatewayQueries
from infrastructure.raw_store.base import RawStore
from infrastructure.raw_store.factory import get_raw_store

log = setup_logger("move_volumes_to_monographs", os.path.dirname(__file__))

_RECORDS = text("""
    SELECT sp.id, sp.source::text AS source, sp.source_id, sp.doi, sp.title, sp.pub_year,
           coalesce(sp.raw_metadata->'doc_type'->>'raw', sp.doc_type) AS raw_doc_type,
           coalesce(sp.meta ? 'conference', false) AS declares_conference,
           sp.external_ids->'isbn' AS isbns, sp.external_ids->'eisbn' AS eisbns,
           normalized.id AS journal_id, sp.monograph_id,
           j.title AS journal_title,
           (SELECT coalesce(json_agg(json_build_object(
                        'issn', i.issn, 'support', i.support, 'linking', i.linking) ORDER BY i.id),
                    '[]')
            FROM journal_issns i
            WHERE i.journal_id = normalized.id AND i.status = 'active') AS journal_issns,
           j.openalex_id,
           j.oa_model::text AS oa_model, j.publisher_id AS journal_publisher_id,
           m.title AS monograph_title, m.publisher_id AS monograph_publisher_id
    FROM source_publications sp
    CROSS JOIN LATERAL (
        SELECT CASE WHEN sp.raw_metadata ? 'journal_id'
                    THEN (sp.raw_metadata->'journal_id'->>'raw')::int
                    ELSE sp.journal_id END AS id
    ) normalized
    LEFT JOIN journals j ON j.id = normalized.id
    LEFT JOIN monographs m ON m.id = sp.monograph_id
    WHERE normalized.id IS NOT NULL OR sp.monograph_id IS NOT NULL
""")


class StoredRecord(NamedTuple):
    """Un enregistrement et ses conteneurs en base."""

    id: int
    source: str
    source_id: str
    doi: str | None
    title: str
    pub_year: int | None
    raw_doc_type: str | None
    declares_conference: bool
    isbns: JsonValue
    eisbns: JsonValue
    journal_id: int | None
    monograph_id: int | None
    journal_title: str | None
    journal_issns: JsonValue
    """ISSN actifs de l'entrée de `journals` : `issn`, `support`, `linking`."""
    openalex_id: str | None
    oa_model: str | None
    journal_publisher_id: int | None
    monograph_title: str | None
    monograph_publisher_id: int | None

    @property
    def has_issn(self) -> bool:
        return bool(self.journal_issns)

    @property
    def role(self) -> ContainerRole:
        return container_role(
            self.raw_doc_type, self.source, declares_conference=self.declares_conference
        )


def _strs(value: JsonValue) -> tuple[str, ...]:
    return (value,) if isinstance(value, str) else tuple(as_strs(value))


def describe(record: StoredRecord) -> ContainerDescription:
    """Description du conteneur d'un enregistrement, reconstruite à partir des champs en base.

    L'entrée de `journals` à ISSN est la collection. Sans ISSN, elle est le livre ou le volume d'actes, à défaut de monographie. Une collection qui porte le titre de la monographie a reçu le titre du volume : elle est seulement cherchée par ISSN.
    """
    collection = record.journal_title if record.has_issn else None
    if (
        collection
        and record.monograph_title
        and normalize_text(collection) == normalize_text(record.monograph_title)
    ):
        collection = None
    book = record.monograph_title or (None if record.has_issn else record.journal_title)
    return ContainerDescription(
        source=record.source,
        raw_doc_type=record.raw_doc_type,
        declares_conference=record.declares_conference,
        document_title=record.monograph_title or record.title,
        journal_title=record.journal_title,
        collection_title=collection,
        book_title=book,
        issns=tuple(
            JournalIssn(
                issn=str(entry["issn"]),
                support=IssnSupport(entry["support"]) if entry["support"] else None,
                linking=bool(entry["linking"]),
            )
            for entry in (as_mapping(e) for e in as_sequence(record.journal_issns))
        ),
        openalex_id=record.openalex_id,
        oa_model=OaModel(record.oa_model) if record.oa_model else None,
        isbns=_strs(record.isbns),
        eisbns=_strs(record.eisbns),
        year=record.pub_year,
    )


def resolve_stored(record: StoredRecord, conn: Connection) -> Containers:
    """Conteneurs d'un enregistrement d'après ses champs en base."""
    return find_or_create_containers(
        describe(record),
        publisher_id=record.monograph_publisher_id or record.journal_publisher_id,
        repo=PgContainerGatewayQueries(conn),
    )


# Rejeu de la normalisation : chaque source lit son éditeur puis ses conteneurs, comme `process_*`.
_Replay = Callable[[Mapping[str, JsonValue], StoredRecord, Connection], Containers]


def _replay_crossref(
    payload: Mapping[str, JsonValue], record: StoredRecord, conn: Connection
) -> Containers:
    publisher_id = normalize_crossref.upsert_publisher(
        payload, publisher_repo=PgPublisherGatewayQueries(conn)
    )
    return normalize_crossref.upsert_containers(
        payload, publisher_id, container_repo=PgContainerGatewayQueries(conn)
    )


def _replay_scanr(
    payload: Mapping[str, JsonValue], record: StoredRecord, conn: Connection
) -> Containers:
    publisher_id = normalize_scanr.upsert_publisher(
        payload, publisher_repo=PgPublisherGatewayQueries(conn)
    )
    return normalize_scanr.upsert_containers(
        payload, publisher_id, container_repo=PgContainerGatewayQueries(conn)
    )


def _replay_hal(
    payload: Mapping[str, JsonValue], record: StoredRecord, conn: Connection
) -> Containers:
    name = hal_text_field(payload.get("journalPublisher_s")) or hal_text_field(
        payload.get("publisher_s")
    )
    publisher_id = (
        normalize_hal.upsert_publisher(name, publisher_repo=PgPublisherGatewayQueries(conn))
        if name
        else None
    )
    return normalize_hal.upsert_containers(
        payload, publisher_id, container_repo=PgContainerGatewayQueries(conn)
    )


def _replay_openalex(
    payload: Mapping[str, JsonValue], record: StoredRecord, conn: Connection
) -> Containers:
    if should_skip_publisher_journal(parse_primary_location(payload)):
        return Containers(None, None)
    publisher_id = normalize_openalex.upsert_publisher(
        payload, publisher_repo=PgPublisherGatewayQueries(conn)
    )
    return normalize_openalex.upsert_containers(
        payload, publisher_id, container_repo=PgContainerGatewayQueries(conn)
    )


def _replay_datacite(
    payload: Mapping[str, JsonValue], record: StoredRecord, conn: Connection
) -> Containers:
    attributes = as_mapping(payload.get("attributes"))
    publisher_id = normalize_datacite.upsert_publisher(
        attributes, publisher_repo=PgPublisherGatewayQueries(conn)
    )
    return normalize_datacite.upsert_containers(
        attributes, publisher_id, container_repo=PgContainerGatewayQueries(conn)
    )


def _replay_wos(
    payload: Mapping[str, JsonValue], record: StoredRecord, conn: Connection
) -> Containers:
    rec = normalize_wos.extract_from_api(payload, record.doi)
    publisher_id = normalize_wos.upsert_publisher(
        as_str(rec.get("publisher_name")), publisher_repo=PgPublisherGatewayQueries(conn)
    )
    return normalize_wos.upsert_containers(
        rec, publisher_id, container_repo=PgContainerGatewayQueries(conn)
    )


_REPLAYS: dict[str, _Replay] = {
    "crossref": _replay_crossref,
    "scanr": _replay_scanr,
    "hal": _replay_hal,
    "openalex": _replay_openalex,
    "datacite": _replay_datacite,
    "wos": _replay_wos,
}


def stratum(record: StoredRecord) -> str:
    """Strate d'audit d'un enregistrement, selon le rôle de son conteneur et son entrée de `journals`."""
    if record.role is ContainerRole.JOURNAL:
        if record.journal_title and is_dated_event_without_issn(
            record.journal_title, has_issn=record.has_issn
        ):
            return "article, conteneur daté sans ISSN"
        return "article de revue"
    if record.journal_id is None:
        return "livre ou partie, sans entrée de journals"
    if record.has_issn:
        return "livre ou partie, collection à ISSN"
    return "livre ou partie, entrée sans ISSN"


def _entry(conn: Connection, table: str, entry_id: int | None) -> str:
    if entry_id is None:
        return "—"
    title = conn.execute(
        text(f"SELECT title FROM {table} WHERE id = :id"), {"id": entry_id}
    ).scalar()  # noqa: S608
    return f"{entry_id} « {title} »"


def _audit(size: int) -> None:
    store: RawStore = get_raw_store()
    engine = get_sync_engine()
    with engine.connect() as conn:
        records = [StoredRecord(*row) for row in conn.execute(_RECORDS)]
    by_stratum: defaultdict[str, list[StoredRecord]] = defaultdict(list)
    for record in records:
        if record.source in _REPLAYS:
            by_stratum[stratum(record)].append(record)

    rng = random.Random(20260921)  # noqa: S311
    tally: Counter[tuple[str, str]] = Counter()
    examples: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    for name, members in sorted(by_stratum.items()):
        rng.shuffle(members)
        audited = 0
        for record in members:
            if audited >= size:
                break
            try:
                payload = json.loads(store.get(record.source, record.source_id))
            except KeyError:
                continue
            audited += 1
            with engine.connect() as conn:
                stored = resolve_stored(record, conn)
                replayed = _REPLAYS[record.source](as_mapping(payload), record, conn)
                gaps = [
                    label
                    for label, a, b in (
                        ("revue", stored.journal_id, replayed.journal_id),
                        ("monographie", stored.monograph_id, replayed.monograph_id),
                    )
                    if a != b
                ]
                verdict = " et ".join(gaps) or "identiques"
                tally[(name, verdict)] += 1
                if gaps and len(examples[(name, verdict)]) < 5:
                    examples[(name, verdict)].append(
                        f"{record.source} {record.source_id} ({record.raw_doc_type}) :"
                        f" base → revue {_entry(conn, 'journals', stored.journal_id)},"
                        f" monographie {_entry(conn, 'monographs', stored.monograph_id)} ;"
                        f" notice → revue {_entry(conn, 'journals', replayed.journal_id)},"
                        f" monographie {_entry(conn, 'monographs', replayed.monograph_id)}"
                    )
                conn.rollback()

    log.info("─── Écart entre le calcul sur la base et la normalisation ───")
    for name in sorted(by_stratum):
        log.info("%s (%d enregistrements)", name, len(by_stratum[name]))
        for (stratum_name, verdict), n in sorted(tally.items()):
            if stratum_name == name:
                log.info("  %-24s %5d", verdict, n)
        for (stratum_name, verdict), lines in sorted(examples.items()):
            if stratum_name == name:
                for line in lines:
                    log.info("    [%s] %s", verdict, line)


_WRITE = text("""
    UPDATE source_publications
    SET journal_id = :journal_id, monograph_id = :monograph_id,
        raw_metadata = raw_metadata - 'journal_id',
        keys_dirty = true, updated_at = clock_timestamp()
    WHERE id = :id
""")

_PROGRESS = 500


def _change(record: StoredRecord, containers: Containers) -> str | None:
    """Nature du changement de conteneurs d'un enregistrement, ou `None` s'il les garde."""
    journal = "" if containers.journal_id == record.journal_id else "revue"
    monograph = "" if containers.monograph_id == record.monograph_id else "monographie"
    return " et ".join(filter(None, (journal, monograph))) or None


def _move(dry_run: bool) -> None:
    store: RawStore = get_raw_store()
    engine = get_sync_engine()
    with engine.connect() as conn:
        records = [StoredRecord(*row) for row in conn.execute(_RECORDS)]
    stored_keys: dict[str, set[str]] = {}
    stock: list[StoredRecord] = []
    for record in records:
        if record.source not in stored_keys:
            stored_keys[record.source] = set(store.iter_keys(record.source))
        if record.source_id not in stored_keys[record.source]:
            stock.append(record)
    log.info("%d enregistrements à conteneur absents du raw store", len(stock))

    tally: Counter[tuple[str, str]] = Counter()
    examples: defaultdict[str, list[str]] = defaultdict(list)
    with engine.connect() as conn:
        for done, record in enumerate(stock, 1):
            containers = resolve_stored(record, conn)
            change = _change(record, containers)
            tally[(record.source, change or "inchangé")] += 1
            if change:
                conn.execute(
                    _WRITE,
                    {
                        "id": record.id,
                        "journal_id": containers.journal_id,
                        "monograph_id": containers.monograph_id,
                    },
                )
                if len(examples[change]) < 10:
                    examples[change].append(
                        f"{record.source} {record.source_id} ({record.raw_doc_type}) :"
                        f" revue {_entry(conn, 'journals', record.journal_id)}"
                        f" → {_entry(conn, 'journals', containers.journal_id)},"
                        f" monographie {_entry(conn, 'monographs', record.monograph_id)}"
                        f" → {_entry(conn, 'monographs', containers.monograph_id)}"
                    )
            if done % _PROGRESS == 0:
                log.info("%d / %d enregistrements traités", done, len(stock))
        if dry_run:
            conn.rollback()
        else:
            conn.commit()

    log.info("─── Changements de conteneurs%s ───", " (dry-run)" if dry_run else "")
    for (source, change), n in sorted(tally.items()):
        log.info("  %-10s %-24s %5d", source, change, n)
    for change, lines in sorted(examples.items()):
        for line in lines:
            log.info("    [%s] %s", change, line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit",
        type=int,
        metavar="N",
        help="Notices du raw store auditées par strate, sans rien écrire.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Calcule sans écrire.")
    args = parser.parse_args()
    if args.audit:
        _audit(args.audit)
    else:
        _move(args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
