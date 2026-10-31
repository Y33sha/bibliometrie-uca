"""Sous-étapes de la phase `publishing` : ISSN des séries, rattachement des enregistrements sources à leur revue.

`sync_issns` donne une ligne de `serial_issns` à chaque ISSN valide d'une série (`biblio.journal`), à vérifier dans le Sudoc.

`attach_serials` applique les règles de `domain.serials.attachment` :

- chaque ISSN reçoit la revue de son ISSN-L. Cette revue est celle de la ligne de l'ISSN-L, à défaut la plus fréquente parmi les ISSN de cet ISSN-L, à défaut une revue créée. Une revue va à un seul ISSN-L ;
- chaque enregistrement source rejoint la revue de l'ISSN-L de ses ISSN, à défaut la revue de son identifiant OpenAlex, à défaut la revue de son titre : décision de l'administration (`serial_title_decisions`), seule revue à ISSN de même titre, revue à ISSN de titre compatible d'un autre enregistrement source de sa publication au run précédent, ou revue sans ISSN de même titre, créée au besoin. L'éditeur départage plusieurs revues à ISSN de même titre ;
- le titre d'une revue est celui de la notice Sudoc de son ISSN-L, à défaut celui d'un autre de ses ISSN, à défaut le plus fréquent parmi ses enregistrements sources. Son identifiant OpenAlex et son modèle OA viennent des enregistrements sources OpenAlex dont l'ISSN-L, d'après OpenAlex, est celui de la revue. Un champ saisi à la main reste inchangé.

Un enregistrement source qui change de revue est marqué pour la réconciliation. Pour un enregistrement source dont la revue est corrigée par la correction des métadonnées, la revue calculée devient la valeur d'avant correction (`corrections.serial_id.raw`). Une revue vidée de ses enregistrements sources, sans ISSN ni monographie, est absorbée par la revue qui en reçoit le plus, avec une redirection.
"""

import json
import logging
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import Connection, Row, text

from domain.normalize import normalize_text, to_plain_text
from domain.publications.identifiers import ISSN
from domain.serials.attachment import (
    TitledSerial,
    choose_issnl,
    effective_issnl,
    match_by_title,
    match_in_publication,
    most_frequent,
    openalex_issnls,
    title_key,
)
from domain.serials.containers import SeriesDescription
from domain.serials.serial import ManualField
from domain.source_records.biblio import journal_series
from domain.source_records.corrections import RAW, CorrectionKey
from infrastructure.db.queues import Queue, enqueue
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.serials.serial_merge import merge_serial_into
from pipeline.transformation.publishing.serials.store import SerialStore

SYNC_LABEL = "ISSN des séries"
"""Libellé de la sous-étape `sync_issns` dans le journal de la phase."""

ATTACH_LABEL = "Rattachement des enregistrements sources aux publications en série"
"""Libellé de la sous-étape `attach_serials` dans le journal de la phase."""

_SERIES = text(f"""
    SELECT id, source, publication_id, publisher_id, biblio->'journal' AS journal,
           CASE WHEN corrections ? '{CorrectionKey.SERIAL_ID}'
                THEN CAST(corrections->'{CorrectionKey.SERIAL_ID}'->>'{RAW}' AS integer)
                ELSE serial_id END AS serial_id
    FROM source_records
    WHERE biblio ? 'journal' OR serial_id IS NOT NULL
""")

_ISSN_ROWS = text("SELECT issn, issnl, serial_id, status FROM serial_issns")

_SERIALS = text("""
    SELECT s.id, s.title, s.title_normalized, s.publisher_id, s.openalex_id, s.manual_fields,
           EXISTS (SELECT 1 FROM serial_issns i WHERE i.serial_id = s.id) AS has_issn
    FROM serials s
""")

_DECISIONS = text("SELECT title_normalized, serial_id FROM serial_title_decisions")

_SET_ISSN_SERIALS = text("""
    UPDATE serial_issns i SET serial_id = t.serial_id
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(issn text, serial_id integer)
    WHERE i.issn = t.issn AND i.serial_id IS DISTINCT FROM t.serial_id
""")

# Une revue corrigée garde sa correction : la revue calculée devient sa valeur d'avant correction, que la correction des métadonnées relit.
_SET_RECORD_SERIALS = text(f"""
    UPDATE source_records s
    SET serial_id = CASE WHEN s.corrections ? '{CorrectionKey.SERIAL_ID}' AND t.serial_id IS NULL
                         THEN s.serial_id ELSE t.serial_id END,
        corrections = CASE WHEN s.corrections ? '{CorrectionKey.SERIAL_ID}'
                           THEN jsonb_set(s.corrections, '{{{CorrectionKey.SERIAL_ID},{RAW}}}',
                                          coalesce(to_jsonb(t.serial_id), 'null'::jsonb))
                           ELSE s.corrections END
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(id integer, serial_id integer)
    WHERE s.id = t.id
""")

_ADD_ISSNS = text("""
    INSERT INTO serial_issns (issn)
    SELECT unnest(CAST(:issns AS text[]))
    ON CONFLICT (issn) DO NOTHING
""")

_UNUSED_SERIALS = text("""
    SELECT s.id FROM serials s
    WHERE s.id = ANY(:ids)
      AND NOT EXISTS (SELECT 1 FROM source_records r WHERE r.serial_id = s.id)
      AND NOT EXISTS (SELECT 1 FROM serial_issns i WHERE i.serial_id = s.id)
      AND NOT EXISTS (SELECT 1 FROM monographs m WHERE m.serial_id = s.id)
""")

_SET_OPENALEX_IDS = text("""
    WITH wanted AS (
        SELECT * FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(id integer, openalex_id text)
    ), freed AS (
        UPDATE serials s SET openalex_id = NULL
        FROM wanted w
        WHERE s.openalex_id = w.openalex_id AND s.id <> w.id
        RETURNING s.id
    )
    SELECT count(*) FROM freed
""")

_WRITE_OPENALEX_IDS = text("""
    UPDATE serials s SET openalex_id = t.openalex_id
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(id integer, openalex_id text)
    WHERE s.id = t.id AND s.openalex_id IS DISTINCT FROM t.openalex_id
""")

_NOTICE_TITLES = text("SELECT issn, sudoc_title FROM serial_issns WHERE sudoc_title IS NOT NULL")

_WRITE_TITLES = text(f"""
    UPDATE serials s SET title = t.title, title_normalized = t.key
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(id integer, title text, key text)
    WHERE s.id = t.id AND s.title IS DISTINCT FROM t.title
      AND NOT '{ManualField.TITLE.value}' = ANY(s.manual_fields)
""")

_WRITE_OA_MODELS = text(f"""
    UPDATE serials s SET oa_model = CAST(t.oa_model AS oa_model)
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(id integer, oa_model text)
    WHERE s.id = t.id AND s.oa_model IS DISTINCT FROM CAST(t.oa_model AS oa_model)
      AND NOT '{ManualField.OA_MODEL.value}' = ANY(s.manual_fields)
""")


@dataclass(slots=True)
class _Mention:
    """Série décrite par un enregistrement source."""

    id: int
    source: str
    publication_id: int | None
    """Publication de l'enregistrement source au run précédent."""
    serial_id: int | None
    """Revue d'avant correction."""
    publisher_id: int | None
    series: SeriesDescription | None
    issns: tuple[str, ...]
    """ISSN valides."""
    openalex_issnl: str | None
    """ISSN-L donné par OpenAlex."""


@dataclass(slots=True)
class _Serial:
    id: int
    title: str
    title_normalized: str
    publisher_id: int | None
    openalex_id: str | None
    manual_fields: list[str]
    has_issn: bool


@dataclass(slots=True)
class _Attachment:
    """Revue de chaque enregistrement source, et compte des rattachements par voie."""

    serial_of: dict[int, int | None] = field(default_factory=dict)
    by_way: Counter[str] = field(default_factory=Counter)


def _valid(value: str) -> str | None:
    issn = ISSN.try_parse(value)
    return str(issn) if issn else None


def _mention(row: Row[tuple[object, ...]]) -> _Mention:
    series = journal_series({"journal": row.journal}) if row.journal else None
    issns = tuple(
        dict.fromkeys(
            v for r in (series.issns if series else ()) if not r.malformed and (v := _valid(r.issn))
        )
    )
    linking = next(
        (v for r in (series.issns if series else ()) if r.linking and (v := _valid(r.issn))), None
    )
    return _Mention(
        id=int(row.id),
        source=str(row.source),
        publication_id=row.publication_id,
        serial_id=row.serial_id,
        publisher_id=row.publisher_id,
        series=series,
        issns=issns,
        openalex_issnl=linking if row.source == "openalex" else None,
    )


def _load_mentions(conn: Connection) -> list[_Mention]:
    return [_mention(r) for r in conn.execute(_SERIES)]


def run_sync_issns(conn: Connection, logger: logging.Logger) -> PhaseMetrics:  # noqa: ARG001
    """Donne une ligne de `serial_issns` aux ISSN valides des séries qui n'en ont pas."""
    known = set(conn.execute(text("SELECT issn FROM serial_issns")).scalars())
    missing = sorted({i for m in _load_mentions(conn) for i in m.issns} - known)
    metrics = PhaseMetrics()
    if missing:
        conn.execute(_ADD_ISSNS, {"issns": missing})
    metrics.add(seen=len(missing), new=len(missing))
    metrics.report = quantity(len(missing), "ISSN ajouté", "ISSN ajoutés")
    return metrics


def _issn_serials(
    conn: Connection, mentions: list[_Mention], oa_issnls: dict[str, str]
) -> tuple[dict[str, str], dict[str, int], int]:
    """Renvoie l'ISSN-L de chaque ISSN, la revue de chaque ISSN-L, et le nombre de revues créées. Écrit la revue de chaque ISSN."""
    rows = {r.issn: r for r in conn.execute(_ISSN_ROWS)}
    issnl_of = {issn: effective_issnl(issn, r.issnl, oa_issnls) for issn, r in rows.items()}
    groups: dict[str, list[str]] = {}
    for issn, issnl in issnl_of.items():
        groups.setdefault(issnl, []).append(issn)
    titles: dict[str, Counter[str]] = {}
    for m in mentions:
        if m.series and m.series.title:
            for issnl in {issnl_of[i] for i in m.issns if i in issnl_of}:
                titles.setdefault(issnl, Counter())[m.series.title] += 1
    used = set(titles) | {
        issnl for issnl, members in groups.items() if any(rows[i].serial_id for i in members)
    }

    serial_of: dict[str, int] = {}
    claimed: set[int] = set()
    # Une revue va d'abord à l'ISSN-L dont la ligne la désigne, puis au plus fréquent parmi ses ISSN.
    for issnl in sorted(used):
        own = rows[issnl].serial_id if issnl in rows else None
        if own is not None and own not in claimed:
            serial_of[issnl] = own
            claimed.add(own)
    store = SerialStore(conn)
    created = 0
    for issnl in sorted(used - set(serial_of)):
        held = Counter(
            rows[i].serial_id
            for i in groups.get(issnl, [])
            if rows[i].serial_id is not None and rows[i].serial_id not in claimed
        )
        if held:
            serial_of[issnl] = most_frequent(held)
        else:
            title = most_frequent(titles[issnl]) if issnl in titles else issnl
            conn.execute(
                text("UPDATE serial_issns SET serial_id = NULL WHERE issn = :i"), {"i": issnl}
            )
            serial_of[issnl] = store.serial_for_issnl(issnl, title)
            created += 1
        claimed.add(serial_of[issnl])
    conn.execute(_ADD_ISSNS, {"issns": sorted(issnl for issnl in serial_of if issnl not in rows)})
    conn.execute(
        _SET_ISSN_SERIALS,
        {
            "rows": json.dumps(
                [
                    {"issn": issn, "serial_id": serial_of.get(issnl)}
                    for issn, issnl in [*issnl_of.items(), *((i, i) for i in serial_of)]
                    if issnl in serial_of
                ]
            )
        },
    )
    return issnl_of, serial_of, created


def _attach(
    conn: Connection,
    mentions: list[_Mention],
    issnl_of: dict[str, str],
    serial_of_issnl: dict[str, int],
) -> _Attachment:
    serials = {
        r.id: _Serial(
            r.id,
            r.title,
            r.title_normalized,
            r.publisher_id,
            r.openalex_id,
            r.manual_fields,
            r.has_issn,
        )
        for r in conn.execute(_SERIALS)
    }
    with_issn = {s.id for s in serials.values() if s.has_issn} | set(serial_of_issnl.values())
    by_openalex = {s.openalex_id: s.id for s in serials.values() if s.openalex_id}
    by_title: dict[str, list[TitledSerial]] = {}
    for s in serials.values():
        if s.id in with_issn:
            by_title.setdefault(s.title_normalized, []).append(TitledSerial(s.id, s.publisher_id))
    decisions = {r.title_normalized: r.serial_id for r in conn.execute(_DECISIONS)}
    result = _Attachment()
    # Séries désignées par leur seul titre, sans revue à ISSN de ce titre : titre et titre normalisé.
    untitled_mentions: list[tuple[_Mention, str, str]] = []
    for m in mentions:
        series = m.series
        if series is None:
            result.serial_of[m.id] = None
            continue
        candidates = {
            issnl: serials[serial_of_issnl[issnl]].title
            for issnl in {issnl_of.get(i, i) for i in m.issns}
            if issnl in serial_of_issnl
        }
        if candidates and (issnl := choose_issnl(series.title, candidates)) is not None:
            result.serial_of[m.id] = serial_of_issnl[issnl]
            result.by_way["issn"] += 1
            continue
        if series.openalex_id and series.openalex_id in by_openalex:
            result.serial_of[m.id] = by_openalex[series.openalex_id]
            result.by_way["openalex"] += 1
            continue
        title_normalized = title_key(series.title)
        if not title_normalized:
            result.serial_of[m.id] = None
            result.by_way["unattached"] += 1
            continue
        found = decisions.get(title_normalized) or match_by_title(
            m.publisher_id, by_title.get(title_normalized, [])
        )
        if found is None:
            untitled_mentions.append((m, str(series.title), title_normalized))
            continue
        result.serial_of[m.id] = found
        result.by_way["title"] += 1
    publication_serials: dict[int, dict[int, str]] = {}
    for m in mentions:
        serial_id = result.serial_of.get(m.id)
        if m.publication_id is not None and serial_id in with_issn:
            publication_serials.setdefault(m.publication_id, {})[serial_id] = serials[
                serial_id
            ].title
    store = SerialStore(conn)
    untitled: dict[str, int] = {}
    for m, title, title_normalized in untitled_mentions:
        in_publication = (
            publication_serials.get(m.publication_id, {}) if m.publication_id is not None else {}
        )
        found = match_in_publication(title, in_publication)
        if found is None:
            if title_normalized not in untitled:
                untitled[title_normalized] = store.serial_for_title(title)
            found = untitled[title_normalized]
        result.serial_of[m.id] = found
        result.by_way["title"] += 1
    return result


def _write_attachment(
    conn: Connection, mentions: list[_Mention], attachment: _Attachment
) -> tuple[list[int], dict[int, Counter[int]]]:
    """Écrit la revue des enregistrements sources qui en changent, et les marque pour la réconciliation. Renvoie ces enregistrements sources, et les revues reçues par les enregistrements sources de chaque revue quittée."""
    changed = [m for m in mentions if attachment.serial_of[m.id] != m.serial_id]
    received: dict[int, Counter[int]] = {}
    for m in changed:
        new = attachment.serial_of[m.id]
        if m.serial_id is not None and new is not None:
            received.setdefault(m.serial_id, Counter())[new] += 1
    if changed:
        ids = [m.id for m in changed]
        conn.execute(
            _SET_RECORD_SERIALS,
            {
                "rows": json.dumps(
                    [{"id": m.id, "serial_id": attachment.serial_of[m.id]} for m in changed]
                )
            },
        )
        enqueue(
            conn, Queue.SOURCE_RECORD_KEYS, "SELECT unnest(CAST(:ids AS integer[]))", {"ids": ids}
        )
    return [m.id for m in changed], received


def _absorb(conn: Connection, received: dict[int, Counter[int]]) -> int:
    """Fusionne chaque revue vidée dans la revue qui a reçu le plus de ses enregistrements sources. Renvoie le nombre de revues absorbées."""
    unused = set(conn.execute(_UNUSED_SERIALS, {"ids": list(received)}).scalars())
    for source_id in sorted(unused):
        merge_serial_into(conn, most_frequent(received[source_id]), source_id)
    return len(unused)


def _notice_titles(conn: Connection, issnl_of: dict[str, str]) -> dict[str, str]:
    """Renvoie le titre de notice Sudoc de chaque ISSN-L : celui de l'ISSN-L lui-même, à défaut celui du plus petit de ses ISSN."""
    by_issn = dict(conn.execute(_NOTICE_TITLES).all())
    titles: dict[str, str] = {}
    for issn in sorted(by_issn):
        issnl = issnl_of.get(issn, issn)
        if issn == issnl or issnl not in titles:
            titles[issnl] = by_issn[issn]
    return titles


def _refresh_attributes(
    conn: Connection,
    mentions: list[_Mention],
    attachment: _Attachment,
    issnl_of: dict[str, str],
    serial_of_issnl: dict[str, int],
) -> None:
    """Écrit le titre, l'identifiant OpenAlex et le modèle OA des revues."""
    issnl_of_serial = {serial_id: issnl for issnl, serial_id in serial_of_issnl.items()}
    titles: dict[int, Counter[str]] = {}
    openalex_ids: dict[int, Counter[str]] = {}
    oa_models: dict[int, Counter[str]] = {}
    for m in mentions:
        serial_id = attachment.serial_of[m.id]
        if serial_id is None or m.series is None:
            continue
        if m.series.title:
            titles.setdefault(serial_id, Counter())[m.series.title] += 1
        own_issnl = issnl_of_serial.get(serial_id)
        if m.source == "openalex" and (
            m.openalex_issnl is None
            or issnl_of.get(m.openalex_issnl, m.openalex_issnl) == own_issnl
        ):
            if m.series.openalex_id:
                openalex_ids.setdefault(serial_id, Counter())[m.series.openalex_id] += 1
            if m.series.oa_model:
                oa_models.setdefault(serial_id, Counter())[m.series.oa_model] += 1
    notice_titles = _notice_titles(conn, issnl_of)
    serial_titles = []
    for serial_id in sorted(set(titles) | set(issnl_of_serial)):
        title = notice_titles.get(issnl_of_serial.get(serial_id, ""))
        if title is None and serial_id in titles:
            title = most_frequent(titles[serial_id])
        if title:
            title = to_plain_text(title)
            serial_titles.append({"id": serial_id, "title": title, "key": normalize_text(title)})
    if serial_titles:
        conn.execute(_WRITE_TITLES, {"rows": json.dumps(serial_titles)})
    # Un identifiant OpenAlex va à une seule revue : celle qui le reçoit de plus d'enregistrements sources.
    votes: dict[str, tuple[int, int]] = {}
    for serial_id, counter in openalex_ids.items():
        openalex_id = most_frequent(counter)
        if openalex_id not in votes or counter[openalex_id] > votes[openalex_id][1]:
            votes[openalex_id] = (serial_id, counter[openalex_id])
    rows = [{"id": serial_id, "openalex_id": oid} for oid, (serial_id, _) in votes.items()]
    if rows:
        conn.execute(_SET_OPENALEX_IDS, {"rows": json.dumps(rows)})
        conn.execute(_WRITE_OPENALEX_IDS, {"rows": json.dumps(rows)})
    models = [{"id": s, "oa_model": most_frequent(c)} for s, c in oa_models.items()]
    if models:
        conn.execute(_WRITE_OA_MODELS, {"rows": json.dumps(models)})


def run_attach_serials(conn: Connection, logger: logging.Logger) -> PhaseMetrics:  # noqa: ARG001
    """Rattache chaque enregistrement source à sa revue, absorbe les revues vidées et écrit les attributs des revues."""
    mentions = _load_mentions(conn)
    oa_issnls = openalex_issnls(
        (m.openalex_issnl, m.issns) for m in mentions if m.openalex_issnl is not None
    )
    issnl_of, serial_of_issnl, created = _issn_serials(conn, mentions, oa_issnls)
    attachment = _attach(conn, mentions, issnl_of, serial_of_issnl)
    changed, received = _write_attachment(conn, mentions, attachment)
    absorbed = _absorb(conn, received)
    _refresh_attributes(conn, mentions, attachment, issnl_of, serial_of_issnl)
    metrics = PhaseMetrics()
    metrics.add(
        seen=len(mentions),
        updated=len(changed),
        new=created,
        serials_absorbed=absorbed,
        attached_by_issn=attachment.by_way["issn"],
        attached_by_openalex=attachment.by_way["openalex"],
        attached_by_title=attachment.by_way["title"],
    )
    metrics.report = (
        f"{quantity(len(changed), 'enregistrement source rattaché', 'enregistrements sources rattachés')} "
        f"à une autre revue, {quantity(absorbed, 'revue absorbée', 'revues absorbées')}"
    )
    return metrics
