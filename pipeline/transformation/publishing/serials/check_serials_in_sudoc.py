"""Sous-étape de la phase `publishing` — vérifie les ISSN des revues dans le Sudoc.

Sont reprises les revues dont un ISSN n'est pas vérifié, les revues dont un enregistrement source a un ISSN absent de leurs ISSN, et les séries d'actes ou collections de livres à ISSN dont le titre a la forme d'un volume. Celles-ci reçoivent leur titre de série (`reference_series_title`) : le titre de la notice Sudoc, à défaut le titre sans ses marques d'édition. Le Sudoc donne la notice de chacun de leurs ISSN, des corrections possibles de leurs valeurs mal formées, et des ISSN d'autre support que ces notices désignent. `domain.serials.issn_check` en tire le support et le statut de chaque ISSN, les ISSN à écarter et les corrections. Chaque ISSN reçoit la date de la vérification.

Les revues passent par `run_fetch_pool` : téléchargements concurrents sur un client HTTP partagé, écritures sérialisées, commit par paquets. Le rythme de la source, posé par l'accès au Sudoc, plafonne le débit, toutes requêtes simultanées confondues. Une revue dont une requête échoue garde ses ISSN non vérifiés : le run suivant la reprend. Les requêtes au Sudoc sont injectées (`pipeline/ingestion/complements/sudoc.py`).
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import NamedTuple

import httpx2
from sqlalchemy import Connection, any_, delete, exists, literal, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from domain.normalize import normalize_text
from domain.publications.identifiers import ISSN
from domain.serials.issn_check import (
    SerialIssns,
    SudocCheck,
    check_serial_issns,
    correction_candidates,
)
from domain.serials.issns import IssnStatus, SerialIssn
from domain.serials.serial import ManualField, SerialType
from domain.serials.series import ContainerLevel, container_level, holds_volumes
from domain.source_records.biblio import BiblioKey, JournalKey
from domain.sources.sudoc import SudocSerialRecord
from infrastructure.db.tables import serial_issns, serials
from infrastructure.repositories.serial_issns import issn_values, issns_by_serial
from pipeline.http.circuit_breaker import SourceUnavailableError, source_tripped
from pipeline.http.fetch_pool import run_fetch_pool
from pipeline.runtime.observability.log_format import BRANCH, inflect, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress
from pipeline.transformation.publishing.serials.store import SerialStore

LABEL = "Vérification des ISSN dans le Sudoc"
"""Libellé de la sous-étape dans le journal de la phase."""

COMMIT_EVERY = 50  # revues par commit

FetchPpns = Callable[[httpx2.AsyncClient, Sequence[str]], Awaitable[dict[str, tuple[str, ...]]]]
"""`(client, issns) -> {issn: ppns}` : PPN des notices Sudoc de chaque ISSN connu du Sudoc."""

FetchRecord = Callable[[httpx2.AsyncClient, str], Awaitable[SudocSerialRecord | None]]
"""`(client, ppn) -> notice`, ou `None` si la notice est introuvable ou illisible."""

# Le sort des ISSN d'une revue tient du détail : le terminal le masque, le journal le garde.
_DETAIL = {"detail": True}


class SerialSudocRow(NamedTuple):
    """Une revue à vérifier dans le Sudoc : son titre, ses ISSN et les ISSN de ses enregistrements sans figurer parmi les siens."""

    id: int
    title: str
    issns: tuple[SerialIssn, ...]
    document_issns: tuple[str, ...] = ()
    serial_type: SerialType = SerialType.UNKNOWN


class SerialTitleTypeRow(NamedTuple):
    """Une revue, son titre et son type."""

    id: int
    title: str
    serial_type: SerialType


# ISSN des enregistrements de chaque revue, toutes sources, tels que reçus : `find_serials_to_check_in_sudoc` les normalise.
_DOCUMENT_ISSNS = text(f"""
    SELECT DISTINCT s.serial_id, trim(v.issn) AS issn
    FROM source_records s
    CROSS JOIN LATERAL (
        VALUES (s.biblio->'{BiblioKey.JOURNAL}'->>'{JournalKey.ISSN}'),
               (s.biblio->'{BiblioKey.JOURNAL}'->>'{JournalKey.EISSN}')
    ) AS v(issn)
    WHERE s.serial_id IS NOT NULL AND v.issn IS NOT NULL
""")

# Revues dont un ISSN n'est pas vérifié dans le Sudoc.
_SERIALS_WITH_UNCHECKED_ISSNS = text("""
    SELECT DISTINCT serial_id FROM serial_issns
    WHERE serial_id IS NOT NULL AND sudoc_checked_at IS NULL
""")


def find_titles_of_serials_with_issn(conn: Connection) -> list[SerialTitleTypeRow]:
    """Les revues qui ont un ISSN actif, avec leur titre et leur type."""
    rows = conn.execute(
        select(serials.c.id, serials.c.title, serials.c.serial_type)
        .where(
            exists().where(
                serial_issns.c.serial_id == serials.c.id,
                serial_issns.c.status == IssnStatus.ACTIVE,
            )
        )
        .order_by(serials.c.id)
    )
    return [SerialTitleTypeRow(r.id, r.title, SerialType(r.serial_type)) for r in rows]


def find_serials_to_check_in_sudoc(
    conn: Connection, also: Sequence[int] = ()
) -> list[SerialSudocRow]:
    """Revues dont un ISSN n'est pas vérifié dans le Sudoc, revues dont un enregistrement a un ISSN valide absent de leurs ISSN et encore jamais vérifié, et revues `also`."""
    issns_of = issns_by_serial(conn)
    released: set[str] = set(
        conn.execute(
            select(serial_issns.c.issn).where(
                serial_issns.c.serial_id.is_(None),
                serial_issns.c.sudoc_checked_at.is_not(None),
            )
        ).scalars()
    )
    documents: dict[int, list[str]] = {}
    for r in conn.execute(_DOCUMENT_ISSNS):
        issn = ISSN.try_parse(r.issn)
        own = issns_of.get(r.serial_id, ())
        if issn is None or str(issn) in released or any(i.issn == str(issn) for i in own):
            continue
        values = documents.setdefault(r.serial_id, [])
        if str(issn) not in values:
            values.append(str(issn))
    ids = set(conn.execute(_SERIALS_WITH_UNCHECKED_ISSNS).scalars()) | set(documents) | set(also)
    # Des ISSN saisis à la main font autorité : la vérification Sudoc passe à côté.
    rows = conn.execute(
        select(serials.c.id, serials.c.title, serials.c.serial_type)
        .where(
            serials.c.id.in_(ids),
            ~(literal(ManualField.ISSNS.value) == any_(serials.c.manual_fields)),
        )
        .order_by(serials.c.id)
    ).all()
    return [
        SerialSudocRow(
            r.id,
            r.title,
            issns_of.get(r.id, ()),
            tuple(sorted(documents.get(r.id, ()))),
            SerialType(r.serial_type),
        )
        for r in rows
    ]


def record_sudoc_check(
    conn: Connection,
    serial_id: int,
    *,
    issns: Sequence[SerialIssn],
    released: Sequence[SerialIssn],
    checked_at: datetime,
    title: str | None = None,
) -> None:
    """Écrit les ISSN vérifiés d'une revue, datés de `checked_at`. `released` : ISSN d'une autre publication, retirés de la revue et gardés sans revue. Un `title` devient le titre de la revue, et une de ses formes de nom."""
    store = SerialStore(conn)
    if store.issns_are_manual(serial_id):
        issns, released = [], []
    else:
        conn.execute(delete(serial_issns).where(serial_issns.c.serial_id == serial_id))
    if issns:
        conn.execute(
            serial_issns.insert(),
            [issn_values(row, serial_id=serial_id, checked_at=checked_at) for row in issns],
        )
    for row in released:
        conn.execute(
            pg_insert(serial_issns)
            .values(issn_values(row, serial_id=None, checked_at=checked_at))
            .on_conflict_do_update(
                constraint="uq_serial_issns_issn_serial",
                set_={"sudoc_checked_at": checked_at},
            )
        )
    # Un titre saisi à la main reste.
    if (
        title
        and conn.execute(
            update(serials)
            .where(
                serials.c.id == serial_id,
                ~(literal(ManualField.TITLE.value) == any_(serials.c.manual_fields)),
            )
            .values(title=title, title_normalized=normalize_text(title))
        ).rowcount
    ):
        publisher_id: int | None = conn.execute(
            select(serials.c.publisher_id).where(serials.c.id == serial_id)
        ).scalar_one()
        store.add_serial_name_form(serial_id, normalize_text(title), publisher_id)


def _serial_issns(row: SerialSudocRow) -> SerialIssns:
    return SerialIssns(
        row.title, row.issns, row.document_issns, holds_volumes=holds_volumes(row.serial_type)
    )


def _adopted(row: SerialSudocRow, check: SudocCheck) -> tuple[str, ...]:
    """ISSN venus des enregistrements de la revue que la vérification rend actifs."""
    active = {r.issn for r in check.issns if r.status is IssnStatus.ACTIVE}
    return tuple(i for i in row.document_issns if i in active)


def _log_check(logger: logging.Logger, row: SerialSudocRow, check: SudocCheck) -> None:
    label = f"Revue {row.id} ({row.title!r})"
    for issn in _adopted(row, check):
        logger.info(
            "%s : ISSN %s d'un enregistrement ajouté à la revue", label, issn, extra=_DETAIL
        )
    if check.conflict:
        logger.info(
            "%s : ISSN de deux publications à égalité — laissés en l'état", label, extra=_DETAIL
        )
    for issn, reason in check.set_aside:
        logger.info("%s : ISSN %s mis de côté (%s)", label, issn, reason, extra=_DETAIL)
    for issn, reason in check.discarded:
        logger.info("%s : ISSN %s écarté (%s)", label, issn, reason, extra=_DETAIL)
    for raw, corrected in check.corrections:
        logger.info("%s : ISSN mal formé %r corrigé en %s", label, raw, corrected, extra=_DETAIL)
    if check.title is not None:
        logger.info("%s : titre de série « %s »", label, check.title, extra=_DETAIL)


async def run_check_serials_in_sudoc(
    conn: Connection,
    logger: logging.Logger,
    *,
    fetch_ppns: FetchPpns,
    fetch_record: FetchRecord,
    max_concurrent: int,
    max_per_run: int | None,
) -> PhaseMetrics:
    """Vérifie les revues à vérifier, `max_concurrent` à la fois. `max_per_run` plafonne le nombre de revues vérifiées, `None` valant illimité : les suivantes attendent le run suivant."""
    titled_as_volumes = [
        j.id
        for j in find_titles_of_serials_with_issn(conn)
        if holds_volumes(j.serial_type) and container_level(j.title) is ContainerLevel.VOLUME
    ]
    rows = find_serials_to_check_in_sudoc(conn, also=titled_as_volumes)
    if max_per_run and len(rows) > max_per_run:
        deferred = len(rows) - max_per_run
        logger.info(
            "%splafond de %s par run ⇒ %s %s au prochain",
            BRANCH,
            quantity(max_per_run, "revue", "revues"),
            deferred,
            inflect(deferred, "reportée"),
        )
        rows = rows[:max_per_run]
    total = len(rows)
    metrics = PhaseMetrics()
    if total == 0:
        return metrics
    metrics.add(seen=total)

    record_by_ppn: dict[str, SudocSerialRecord | None] = {}

    async def _read(
        client: httpx2.AsyncClient, issns: Sequence[str], records: dict[str, SudocSerialRecord]
    ) -> None:
        """Ajoute à `records` la notice de chaque ISSN connu du Sudoc. `record_by_ppn` garde les notices déjà lues."""
        ppns_by_issn = await fetch_ppns(client, issns)
        for issn in issns:
            if not (ppns := ppns_by_issn.get(issn)):
                continue
            if ppns[0] not in record_by_ppn:
                record_by_ppn[ppns[0]] = await fetch_record(client, ppns[0])
            if (record := record_by_ppn[ppns[0]]) is not None:
                records[issn] = record

    async def _fetch(
        client: httpx2.AsyncClient, row: SerialSudocRow
    ) -> dict[str, SudocSerialRecord] | None:
        """Notices utiles à la vérification de la revue, ou `None` si une requête a échoué."""
        serial = _serial_issns(row)
        issns = (*serial.examined(), *correction_candidates(serial.malformed()))
        records: dict[str, SudocSerialRecord] = {}
        try:
            await _read(client, issns, records)
            # L'ISSN d'autre support qu'une notice désigne complète une colonne vide : sa propre notice donne son support.
            others = list(
                dict.fromkeys(
                    x for r in records.values() for x in r.other_support_issns if x not in issns
                )
            )
            if others:
                await _read(client, others, records)
        except (httpx2.HTTPError, SourceUnavailableError) as exc:
            logger.warning(
                "Revue %d : requête Sudoc en échec, reprise au prochain run (%s)", row.id, exc
            )
            return None
        return records

    # Le compteur de la barre compte les revues présentes dans le Sudoc.
    with track_progress(total, f"{BRANCH}{LABEL}", logger, count_kept=True, erase=True) as progress:

        def _write(
            conn: Connection, row: SerialSudocRow, records: dict[str, SudocSerialRecord] | None
        ) -> None:
            progress.advance()
            if records is None:
                metrics.add(errors=1)
                return
            check = check_serial_issns(_serial_issns(row), records)
            _log_check(logger, row, check)
            record_sudoc_check(
                conn,
                row.id,
                issns=check.issns,
                released=check.released,
                checked_at=datetime.now(UTC),
                title=check.title,
            )
            changed = set(check.issns) != set(row.issns) or bool(check.released)
            metrics.add(
                updated=int(changed),
                unchanged=int(not changed),
                sudoc_found=int(check.found),
                issn_set_aside=len(check.set_aside),
                issn_discarded=len(check.discarded),
                issn_corrected=len(check.corrections),
                issn_conflicts=int(check.conflict),
                issn_from_documents=len(_adopted(row, check)),
                series_titled=int(check.title is not None),
            )
            progress.keep(int(check.found))

        await run_fetch_pool(
            rows,
            conn,
            max_concurrent=max_concurrent,
            commit_every=COMMIT_EVERY,
            fetch=_fetch,
            write=_write,
        )

    checked = metrics.updated + metrics.unchanged
    if source_tripped():
        logger.warning(
            "⚡ Coupe-circuit Sudoc : vérification interrompue à %d/%d, reste repris au prochain run.",
            checked,
            total,
        )
    found = metrics.extras.get("sudoc_found", 0)
    metrics.report = (
        f"{quantity(total, 'revue vérifiée', 'revues vérifiées')}, "
        f"{quantity(found, 'présente', 'présentes')} dans le Sudoc, "
        f"{metrics.updated} {inflect(metrics.updated, 'modifiée')}"
    )
    return metrics
