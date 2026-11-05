"""Sous-étapes de la phase `publishing` : ISSN des séries, rattachement des enregistrements sources à leur revue.

`sync_issns` donne une ligne de `serial_issns` à chaque ISSN valide d'une série (`biblio.journal`), à vérifier dans le Sudoc.

`attach_serials` applique les règles de `domain.serials.attachment` :

- chaque ISSN reçoit la revue de son ISSN-L : celui de la table de l'ISSN International Centre (`import_issnl_table`), à défaut celui de l'ISSN qui l'annule d'après le Sudoc, à défaut celui d'OpenAlex, à défaut l'ISSN lui-même. Cette revue est celle de la ligne de l'ISSN-L, à défaut la plus fréquente parmi les ISSN de cet ISSN-L, à défaut une revue créée. Une revue va à un seul ISSN-L ;
- chaque enregistrement source rejoint la revue de l'ISSN-L de ses ISSN, à défaut la revue de son identifiant OpenAlex, à défaut la revue de son titre : décision de l'administration (`serial_title_decisions`), seule revue à ISSN de même titre, revue à ISSN de titre compatible d'un autre enregistrement source de sa publication au run précédent, ou revue sans ISSN de même titre, créée au besoin. L'éditeur départage plusieurs revues à ISSN de même titre ;
- le titre d'une revue est celui de la notice Sudoc de son ISSN-L, à défaut celui d'un autre de ses ISSN, à défaut le plus fréquent parmi ses enregistrements sources. Son modèle OA vient des enregistrements sources OpenAlex dont l'ISSN-L, d'après OpenAlex, est celui de la revue. Un champ saisi à la main reste inchangé.

Un enregistrement source qui change de revue est marqué pour la réconciliation. Pour un enregistrement source dont la revue est corrigée par la correction des métadonnées, la revue calculée devient la valeur d'avant correction (`corrections.serial_id.raw`). Une revue vidée de ses enregistrements sources, sans ISSN ni monographie, est absorbée par la revue qui en reçoit le plus, avec une redirection.
"""

import json
import logging
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy import Connection, Row, text

from domain.documents.identifiers import ISSN
from domain.entity_resolution import most_frequent
from domain.normalize import normalize_text
from domain.serials.attachment import (
    IssnlPlan,
    KnownIssn,
    KnownSerial,
    NewSerial,
    SerialAttachment,
    SerialRef,
    SeriesMention,
    openalex_issnls,
    plan_issnl_serials,
    plan_record_serials,
)
from domain.serials.containers import SeriesDescription
from domain.serials.serial import ManualField
from domain.source_records.biblio import journal_series
from domain.source_records.corrections import RAW, CorrectionKey
from infrastructure.sql_fragments import corrected, stashed_raw
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.serials.serial_merge import merge_serial_into
from pipeline.transformation.publishing.serials.store import SerialStore
from pipeline.transformation.publishing.source_record_links import write_links

SYNC_LABEL = "ISSN des séries"
"""Libellé de la sous-étape `sync_issns` dans le journal de la phase."""

ATTACH_LABEL = "Rattachement des enregistrements sources aux publications en série"
"""Libellé de la sous-étape `attach_serials` dans le journal de la phase."""

_SERIES = text(f"""
    SELECT id, source, publication_id, publisher_id, biblio,
           CASE WHEN {corrected(CorrectionKey.SERIAL_ID, "source_records")}
                THEN CAST({stashed_raw(CorrectionKey.SERIAL_ID, "source_records")} AS integer)
                ELSE serial_id END AS serial_id
    FROM source_records
    WHERE biblio ? 'journal' OR serial_id IS NOT NULL
""")

_ISSN_ROWS = text("SELECT issn, issnl, serial_id, status FROM serial_issns")

_REPLACEMENTS = text("SELECT issn, linked_issn FROM issn_links WHERE link_type = 'replaced_by'")

_SERIALS = text("SELECT id, title, title_normalized, publisher_id, openalex_id FROM serials")

_DECISIONS = text("SELECT title_normalized, serial_id FROM serial_title_decisions")

_SET_ISSN_SERIALS = text("""
    UPDATE serial_issns i SET serial_id = t.serial_id
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(issn text, serial_id integer)
    WHERE i.issn = t.issn AND i.serial_id IS DISTINCT FROM t.serial_id
""")

_SET_RECORD_SERIALS = text(f"""
    UPDATE source_records s
    SET serial_id = CASE WHEN {corrected(CorrectionKey.SERIAL_ID, "s")} AND t.serial_id IS NULL
                         THEN s.serial_id ELSE t.serial_id END,
        corrections = CASE WHEN {corrected(CorrectionKey.SERIAL_ID, "s")}
                           THEN jsonb_set(s.corrections, '{{{CorrectionKey.SERIAL_ID},{RAW}}}',
                                          coalesce(to_jsonb(t.serial_id), 'null'::jsonb))
                           ELSE s.corrections END
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(id integer, serial_id integer)
    WHERE s.id = t.id
""")
"""Une revue corrigée garde sa correction : la revue calculée devient sa valeur d'avant correction, que la correction des métadonnées relit."""

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
class _Attachment:
    """Revue de chaque enregistrement source, et compte des rattachements par voie."""

    serial_of: dict[int, int | None] = field(default_factory=dict)
    by_way: Counter[str] = field(default_factory=Counter)


def _valid(value: str) -> str | None:
    issn = ISSN.try_parse(value)
    return str(issn) if issn else None


def _mention(row: Row[tuple[object, ...]]) -> _Mention:
    series = journal_series(row.biblio)
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


def _plan(
    conn: Connection, mentions: list[_Mention], issns: Mapping[str, KnownIssn]
) -> tuple[IssnlPlan, SerialAttachment]:
    """Renvoie la revue de chaque ISSN-L et celle de chaque enregistrement source, d'après les faits en base, sans rien écrire."""
    oa_issnls = openalex_issnls(
        (m.openalex_issnl, m.issns) for m in mentions if m.openalex_issnl is not None
    )
    issnl_plan = plan_issnl_serials(
        issns,
        {r.issn: r.linked_issn for r in conn.execute(_REPLACEMENTS)},
        oa_issnls,
        ((m.issns, m.series.title) for m in mentions if m.series),
    )
    record_plan = plan_record_serials(
        [
            SeriesMention(
                m.id,
                m.publication_id,
                m.publisher_id,
                m.series.title,
                m.series.openalex_id,
                m.issns,
            )
            for m in mentions
            if m.series
        ],
        issnl_plan,
        {
            r.id: KnownSerial(r.title, r.title_normalized, r.publisher_id, r.openalex_id)
            for r in conn.execute(_SERIALS)
        },
        {r.title_normalized: r.serial_id for r in conn.execute(_DECISIONS)},
    )
    return issnl_plan, record_plan


def _write_issn_serials(
    conn: Connection,
    issns: Mapping[str, KnownIssn],
    issnl_of: Mapping[str, str],
    serial_of_issnl: Mapping[str, int],
) -> None:
    """Écrit la revue de chaque ISSN, celle de son ISSN-L. Un ISSN-L absent des ISSN connus reçoit sa ligne."""
    conn.execute(
        _ADD_ISSNS, {"issns": sorted(issnl for issnl in serial_of_issnl if issnl not in issns)}
    )
    conn.execute(
        _SET_ISSN_SERIALS,
        {
            "rows": json.dumps(
                [
                    {"issn": issn, "serial_id": serial_of_issnl[issnl]}
                    for issn, issnl in [*issnl_of.items(), *((i, i) for i in serial_of_issnl)]
                    if issnl in serial_of_issnl
                ]
            )
        },
    )


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
    write_links(
        conn,
        "serial_id",
        {m.id: attachment.serial_of[m.id] for m in changed},
        update=_SET_RECORD_SERIALS,
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
    """Écrit le titre et le modèle OA des revues."""
    issnl_of_serial = {serial_id: issnl for issnl, serial_id in serial_of_issnl.items()}
    titles: dict[int, Counter[str]] = {}
    oa_models: dict[int, Counter[str]] = {}
    for m in mentions:
        serial_id = attachment.serial_of[m.id]
        if serial_id is None or m.series is None:
            continue
        if m.series.title:
            titles.setdefault(serial_id, Counter())[m.series.title] += 1
        own_issnl = issnl_of_serial.get(serial_id)
        if (
            m.source == "openalex"
            and m.series.oa_model
            and (
                m.openalex_issnl is None
                or issnl_of.get(m.openalex_issnl, m.openalex_issnl) == own_issnl
            )
        ):
            oa_models.setdefault(serial_id, Counter())[m.series.oa_model] += 1
    notice_titles = _notice_titles(conn, issnl_of)
    serial_titles = []
    for serial_id in sorted(set(titles) | set(issnl_of_serial)):
        title = notice_titles.get(issnl_of_serial.get(serial_id, ""))
        if title is None and serial_id in titles:
            title = most_frequent(titles[serial_id])
        if title:
            serial_titles.append({"id": serial_id, "title": title, "key": normalize_text(title)})
    if serial_titles:
        conn.execute(_WRITE_TITLES, {"rows": json.dumps(serial_titles)})
    models = [{"id": s, "oa_model": most_frequent(c)} for s, c in oa_models.items()]
    if models:
        conn.execute(_WRITE_OA_MODELS, {"rows": json.dumps(models)})


def run_attach_serials(conn: Connection, logger: logging.Logger) -> PhaseMetrics:  # noqa: ARG001
    """Rattache chaque enregistrement source à sa revue, absorbe les revues vidées et écrit les attributs des revues.

    Le plan se calcule d'abord sur les faits en base. Les revues à créer du plan sont créées ensuite, puis les liens écrits.
    """
    mentions = _load_mentions(conn)
    issns = {r.issn: KnownIssn(r.issnl, r.serial_id) for r in conn.execute(_ISSN_ROWS)}
    issnl_plan, record_plan = _plan(conn, mentions, issns)

    store = SerialStore(conn)
    created: dict[NewSerial, int] = {}

    def resolve(serial: SerialRef) -> int:
        if not isinstance(serial, NewSerial):
            return serial
        if serial not in created:
            created[serial] = store.create_serial(serial.title)
        return created[serial]

    issnl_of = issnl_plan.issnl_of
    serial_of_issnl = {issnl: resolve(serial) for issnl, serial in issnl_plan.serial_of.items()}
    _write_issn_serials(conn, issns, issnl_of, serial_of_issnl)
    attachment = _Attachment(by_way=record_plan.by_way)
    for m in mentions:
        serial = record_plan.serial_of[m.id] if m.series else None
        attachment.serial_of[m.id] = resolve(serial) if serial is not None else None
    changed, received = _write_attachment(conn, mentions, attachment)
    absorbed = _absorb(conn, received)
    _refresh_attributes(conn, mentions, attachment, issnl_of, serial_of_issnl)
    metrics = PhaseMetrics()
    metrics.add(
        seen=len(mentions),
        updated=len(changed),
        new=len(created),
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
