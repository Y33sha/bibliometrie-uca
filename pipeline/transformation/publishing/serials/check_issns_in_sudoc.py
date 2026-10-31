"""Sous-étape de la phase `publishing` : vérification des ISSN dans le Sudoc.

Sont vérifiés les ISSN de `serial_issns` jamais vérifiés. La notice Sudoc de chaque ISSN donne son ISSN-L, son support et son statut, ceux de ses ISSN annulés, et ses liens vers d'autres ISSN (`read_sudoc_record`). Les ISSN de la même publication sur un autre support reçoivent leur ligne, vérifiée au run suivant. La revue de l'ISSN-L reçoit le titre de la notice Sudoc, sauf titre saisi à la main : elle est créée si elle manque (`serial_for_issnl`).

Les ISSN passent par lots de `SUDOC_ISSN2PPN_BATCH` dans `run_fetch_pool` : téléchargements concurrents sur un client HTTP partagé, écritures sérialisées, commit par paquets. Si une requête échoue, les ISSN du lot restent non vérifiés et le run suivant les reprend. Les requêtes au Sudoc sont injectées (`pipeline/ingestion/complements/sudoc.py`).
"""

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

import httpx2
from sqlalchemy import Connection, select, text

from domain.serials.issn_facts import SudocReading, read_sudoc_record
from domain.sources.sudoc import SudocSerialRecord
from infrastructure.db.tables import serial_issns
from pipeline.http.circuit_breaker import SourceUnavailableError, source_tripped
from pipeline.http.fetch_pool import run_fetch_pool
from pipeline.ingestion.api_params import SUDOC_ISSN2PPN_BATCH
from pipeline.runtime.observability.log_format import BRANCH, inflect, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress
from pipeline.transformation.publishing.serials.store import SerialStore

LABEL = "Vérification des ISSN dans le Sudoc"
"""Libellé de la sous-étape dans le journal de la phase."""

COMMIT_EVERY = 10  # lots d'ISSN par commit

FetchPpns = Callable[[httpx2.AsyncClient, Sequence[str]], Awaitable[dict[str, tuple[str, ...]]]]
"""`(client, issns) -> {issn: ppns}` : PPN des notices Sudoc de chaque ISSN connu du Sudoc."""

FetchRecord = Callable[[httpx2.AsyncClient, str], Awaitable[SudocSerialRecord | None]]
"""`(client, ppn) -> notice Sudoc`, ou `None` si la notice Sudoc est introuvable ou illisible."""

_WRITE_FACTS = text("""
    INSERT INTO serial_issns (issn, issnl, support, status, sudoc_checked_at)
    SELECT f.issn, f.issnl, CAST(f.support AS issn_support), CAST(f.status AS issn_status),
           CAST(:checked_at AS timestamptz)
    FROM jsonb_to_recordset(CAST(:facts AS jsonb))
        AS f(issn text, issnl text, support text, status text)
    ON CONFLICT (issn) DO UPDATE SET
        issnl = EXCLUDED.issnl,
        support = coalesce(EXCLUDED.support, serial_issns.support),
        status = EXCLUDED.status,
        sudoc_checked_at = EXCLUDED.sudoc_checked_at
""")

_WRITE_LINKS = text("""
    INSERT INTO issn_links (issn, linked_issn, link_type)
    SELECT l.issn, l.linked_issn, CAST(l.link_type AS issn_link_type)
    FROM jsonb_to_recordset(CAST(:links AS jsonb)) AS l(issn text, linked_issn text, link_type text)
    ON CONFLICT DO NOTHING
""")

_ADD_ISSNS = text("""
    INSERT INTO serial_issns (issn)
    SELECT unnest(CAST(:issns AS text[]))
    ON CONFLICT (issn) DO NOTHING
""")


def find_issns_to_check(conn: Connection) -> list[str]:
    """Renvoie les ISSN jamais vérifiés dans le Sudoc."""
    return list(
        conn.execute(
            select(serial_issns.c.issn)
            .where(serial_issns.c.sudoc_checked_at.is_(None))
            .order_by(serial_issns.c.issn)
        ).scalars()
    )


def record_sudoc_reading(
    conn: Connection, issn: str, reading: SudocReading, checked_at: datetime
) -> None:
    """Écrit les faits et les liens tirés de la notice Sudoc de `issn`, et le titre de la revue de son ISSN-L."""
    conn.execute(
        _WRITE_FACTS,
        {
            "checked_at": checked_at,
            "facts": json.dumps(
                [
                    {"issn": f.issn, "issnl": f.issnl, "support": f.support, "status": f.status}
                    for f in reading.facts
                ]
            ),
        },
    )
    if reading.links:
        conn.execute(
            _WRITE_LINKS,
            {
                "links": json.dumps(
                    [
                        {"issn": x.issn, "linked_issn": x.linked_issn, "link_type": x.link_type}
                        for x in reading.links
                    ]
                )
            },
        )
    if reading.other_support_issns:
        conn.execute(_ADD_ISSNS, {"issns": list(reading.other_support_issns)})
    if reading.title:
        store = SerialStore(conn)
        serial_id = store.serial_for_issnl(reading.issnl or issn, reading.title)
        store.set_title(serial_id, reading.title)


async def run_check_issns_in_sudoc(
    conn: Connection,
    logger: logging.Logger,
    *,
    fetch_ppns: FetchPpns,
    fetch_record: FetchRecord,
    max_concurrent: int,
    max_per_run: int | None,
) -> PhaseMetrics:
    """Vérifie dans le Sudoc les ISSN jamais vérifiés, `max_concurrent` lots à la fois.

    Args:
        max_per_run: plafond d'ISSN vérifiés, `None` pour illimité ; les suivants attendent le run suivant.
    """
    issns = find_issns_to_check(conn)
    if max_per_run and len(issns) > max_per_run:
        deferred = len(issns) - max_per_run
        logger.info(
            "%splafond de %s par run ⇒ %s %s au prochain",
            BRANCH,
            quantity(max_per_run, "ISSN", "ISSN"),
            deferred,
            inflect(deferred, "reporté"),
        )
        issns = issns[:max_per_run]
    metrics = PhaseMetrics()
    if not issns:
        return metrics
    metrics.add(seen=len(issns))
    batches = [
        tuple(issns[i : i + SUDOC_ISSN2PPN_BATCH])
        for i in range(0, len(issns), SUDOC_ISSN2PPN_BATCH)
    ]
    record_by_ppn: dict[str, SudocSerialRecord | None] = {}

    async def _fetch(
        client: httpx2.AsyncClient, batch: tuple[str, ...]
    ) -> dict[str, SudocSerialRecord] | None:
        """Renvoie la notice Sudoc de chaque ISSN du lot connu du Sudoc, ou `None` si une requête a échoué."""
        records: dict[str, SudocSerialRecord] = {}
        try:
            ppns_by_issn = await fetch_ppns(client, batch)
            for issn in batch:
                if not (ppns := ppns_by_issn.get(issn)):
                    continue
                if ppns[0] not in record_by_ppn:
                    record_by_ppn[ppns[0]] = await fetch_record(client, ppns[0])
                if (record := record_by_ppn[ppns[0]]) is not None:
                    records[issn] = record
        except (httpx2.HTTPError, SourceUnavailableError) as exc:
            logger.warning(
                "Lot de %d ISSN : requête Sudoc en échec, reprise au prochain run (%s)",
                len(batch),
                exc,
            )
            return None
        return records

    # Le compteur de la barre compte les ISSN présents dans le Sudoc.
    with track_progress(
        len(issns), f"{BRANCH}{LABEL}", logger, count_kept=True, erase=True
    ) as progress:

        def _write(
            conn: Connection, batch: tuple[str, ...], records: dict[str, SudocSerialRecord] | None
        ) -> None:
            progress.advance(len(batch))
            if records is None:
                metrics.add(errors=len(batch))
                return
            checked_at = datetime.now(UTC)
            for issn in batch:
                reading = read_sudoc_record(issn, records.get(issn))
                record_sudoc_reading(conn, issn, reading, checked_at)
            metrics.add(updated=len(batch), sudoc_found=len(records))
            progress.keep(len(records))

        await run_fetch_pool(
            batches,
            conn,
            max_concurrent=max_concurrent,
            commit_every=COMMIT_EVERY,
            fetch=_fetch,
            write=_write,
        )

    if source_tripped():
        logger.warning(
            "⚡ Coupe-circuit Sudoc : vérification interrompue à %d/%d ISSN, reste repris au prochain run.",
            metrics.updated,
            len(issns),
        )
    found = metrics.extras.get("sudoc_found", 0)
    metrics.report = (
        f"{quantity(metrics.updated, 'ISSN vérifié', 'ISSN vérifiés')}, "
        f"{quantity(found, 'présent', 'présents')} dans le Sudoc"
    )
    return metrics
