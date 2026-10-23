"""Phase `oa_status` : verdicts d'Unpaywall sur les DOI des publications (`sources.unpaywall`), et statut open access qui en découle (`publications.oa_status`).

La phase interroge Unpaywall pour les DOI jamais vérifiés ou périmés, et écrit chaque verdict. Un DOI absent d'Unpaywall reçoit un verdict nul. Quand Unpaywall est indisponible, le DOI attend le run suivant. Le statut des publications de ces DOI se recalcule ensuite par `publication_oa_status`, à partir de leurs enregistrements sources et du verdict.

Le délai de péremption et le plafond par run bornent la phase : le retard des DOI jamais vérifiés s'écoule d'un run à l'autre. La phase passe par l'accès à Unpaywall, qui exige l'adresse du polite pool.

Implémentation async : `httpx2.AsyncClient` partagé + `asyncio.Semaphore(5)` sous le seuil Unpaywall (~10 req/s recommandé).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import NamedTuple

import httpx2
from sqlalchemy import Connection, text

from domain.config import ConfigKey
from domain.publications.metadata import OaStatus, publication_oa_status
from infrastructure.db.scalars import scalar_int
from pipeline.http.lookup import LookupOutcome, NotFound, Unavailable
from pipeline.http.polite_pool import get_polite_pool_email_optional
from pipeline.http.tls import tls_context
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.complements.unpaywall import fetch_oa_status
from pipeline.runtime.config import cap, delay
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.log_format import (
    BRANCH,
    LAST_BRANCH,
    inflect,
    nothing_to_do,
    quantity,
    step,
)
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress
from pipeline.task_runner import SingleTaskPhase

type OaStatusFetcher = Callable[[httpx2.AsyncClient, str], Awaitable[LookupOutcome[str]]]
"""Signature : `(client, doi) → statut OA mappé, NOT_FOUND ou UNAVAILABLE`."""

# Constantes opérationnelles.
BATCH_SIZE = 50
MAX_CONCURRENT = 5


class OaSignal(NamedTuple):
    """Source et statut OA d'un enregistrement source d'une publication."""

    source: str
    oa_status: str | None


class PublicationOaInputs(NamedTuple):
    """Ce dont dépend le statut OA d'une publication : son DOI, son statut courant, les statuts de ses enregistrements sources."""

    id: int
    doi: str
    oa_status: str | None
    signals: list[OaSignal]


# DOI des publications sans verdict d'Unpaywall, ou dont le verdict date de plus de `:stale` jours.
_STALE_DOIS = """
    SELECT d.doi, u.checked_at
    FROM (SELECT DISTINCT lower(doi) AS doi FROM publications WHERE doi IS NOT NULL) d
    LEFT JOIN unpaywall u ON u.doi = d.doi
    WHERE u.doi IS NULL OR u.checked_at < now() - make_interval(days => :stale)
"""


class OaStatusStore:
    """DOI à vérifier sur Unpaywall, verdicts reçus, statut OA des publications."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def fetch_dois_to_check(self, *, limit: int | None = None, staleness_days: int) -> list[str]:
        """DOI à vérifier sur Unpaywall : jamais vérifiés d'abord, puis les plus périmés. `limit` plafonne le run."""
        rows = self._conn.execute(
            text(f"{_STALE_DOIS} ORDER BY checked_at ASC NULLS FIRST, doi LIMIT :lim"),
            {"stale": staleness_days, "lim": limit},
        )
        return [r.doi for r in rows]

    def count_dois_to_check(self, *, staleness_days: int) -> int:
        """Nombre de DOI à vérifier, sans plafond."""
        return scalar_int(
            self._conn.execute(
                text(f"SELECT count(*) FROM ({_STALE_DOIS}) s"), {"stale": staleness_days}
            )
        )

    def fetch_verdicts(self, dois: Sequence[str]) -> dict[str, str | None]:
        """Verdict en table de chacun de ces DOI, quand il en a un."""
        rows = self._conn.execute(
            text("SELECT doi, oa_status::text AS oa_status FROM unpaywall WHERE doi = ANY(:dois)"),
            {"dois": list(dois)},
        )
        return {r.doi: r.oa_status for r in rows}

    def record_verdicts(self, verdicts: Sequence[tuple[str, str | None]]) -> None:
        """Écrit le verdict d'Unpaywall de chaque DOI, `None` pour un DOI absent d'Unpaywall, daté de l'instant."""
        if not verdicts:
            return
        self._conn.execute(
            text("""
                INSERT INTO unpaywall (doi, oa_status, checked_at)
                SELECT v.doi, CAST(v.oa_status AS oa_type), now()
                FROM unnest(CAST(:dois AS text[]), CAST(:statuses AS text[])) AS v(doi, oa_status)
                ON CONFLICT (doi) DO UPDATE
                SET oa_status = EXCLUDED.oa_status, checked_at = EXCLUDED.checked_at
            """),
            {"dois": [d for d, _ in verdicts], "statuses": [s for _, s in verdicts]},
        )

    def fetch_oa_inputs(self, dois: Sequence[str]) -> list[PublicationOaInputs]:
        """Publications de ces DOI, avec les statuts OA de leurs enregistrements sources."""
        rows = self._conn.execute(
            text("""
                SELECT p.id, lower(p.doi) AS doi, p.oa_status::text AS oa_status,
                       array_agg(sr.source::text ORDER BY sr.id) AS sources,
                       array_agg(sr.oa_status::text ORDER BY sr.id) AS statuses
                FROM publications p
                JOIN source_records sr ON sr.publication_id = p.id
                WHERE lower(p.doi) = ANY(:dois)
                GROUP BY p.id
            """),
            {"dois": list(dois)},
        )
        return [
            PublicationOaInputs(
                r.id,
                r.doi,
                r.oa_status,
                [OaSignal(s, o) for s, o in zip(r.sources, r.statuses, strict=True)],
            )
            for r in rows
        ]

    def update_oa_status(self, publication_id: int, oa_status: str) -> None:
        """Écrit le statut OA d'une publication."""
        self._conn.execute(
            text(
                "UPDATE publications SET oa_status = CAST(:os AS oa_type), updated_at = now()"
                " WHERE id = :id"
            ),
            {"os": oa_status, "id": publication_id},
        )

    def count_publications_by_oa_status(self) -> dict[str, int]:
        """Répartition des publications par statut OA (`oa_status` → nombre)."""
        rows = self._conn.execute(
            text(
                f"SELECT COALESCE(oa_status::text, '{OaStatus.UNKNOWN.value}') AS status, count(*) AS n "
                f"FROM publications GROUP BY COALESCE(oa_status::text, '{OaStatus.UNKNOWN.value}')"
            )
        ).all()
        return {r.status: int(r.n) for r in rows}


@dataclass(frozen=True)
class OaStatusPhase:
    """Vérifie sur Unpaywall le statut OA des publications à DOI.

    `staleness_days` lit le délai, en jours, au-delà duquel un DOI vérifié l'est de nouveau. `max_per_run` lit le plafond de DOI vérifiés par run, `None` valant illimité.
    """

    fetcher: OaStatusFetcher
    staleness_days: Callable[[Connection], int]
    max_per_run: Callable[[Connection], int | None]
    max_concurrent: int = MAX_CONCURRENT
    store_factory: Callable[[Connection], OaStatusStore] = OaStatusStore

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Vérifie les DOI dans une seule transaction, avec un commit par paquet."""
        metrics = PhaseMetrics()
        with ctx.open_tx() as conn:
            metrics.merge(
                asyncio.run(
                    _check(
                        conn,
                        self.store_factory(conn),
                        ctx.logger,
                        fetcher=self.fetcher,
                        staleness_days=self.staleness_days(conn),
                        max_per_run=self.max_per_run(conn),
                        max_concurrent=self.max_concurrent,
                    )
                )
            )
        return metrics


async def _check(
    conn: Connection,
    store: OaStatusStore,
    logger: logging.Logger,
    *,
    fetcher: OaStatusFetcher,
    staleness_days: int,
    max_per_run: int | None,
    max_concurrent: int,
) -> PhaseMetrics:
    """Interroge Unpaywall pour les DOI à vérifier, écrit les verdicts, recalcule le statut OA des publications de ces DOI, puis rend les métriques du run."""
    metrics = PhaseMetrics()
    dois = store.fetch_dois_to_check(limit=max_per_run, staleness_days=staleness_days)
    total = len(dois)
    stale_total = store.count_dois_to_check(staleness_days=staleness_days)
    before_dist = store.count_publications_by_oa_status()

    progress = {"new": 0, "updated": 0, "unchanged": 0, "not_found": 0, "unavailable": 0}

    def _result() -> PhaseMetrics:
        # Indicateurs : verdicts du run (nouveaux, modifiés, inchangés, non trouvés), puis répartition des publications par statut OA avec le delta du run (avant → après).
        metrics.add(
            seen=total,
            new=progress["new"],
            updated=progress["updated"],
            unchanged=progress["unchanged"],
            not_found=progress["not_found"],
            errors=progress["unavailable"],
        )
        after_dist = store.count_publications_by_oa_status()
        statuses = sorted(
            set(before_dist) | set(after_dist),
            key=lambda s: after_dist.get(s, 0),
            reverse=True,
        )
        metrics.details["summary"] = {
            "stale": stale_total,
            "checked": total,
            "new": progress["new"],
            "updated": progress["updated"],
            "unchanged": progress["unchanged"],
            "not_found": progress["not_found"],
            "unavailable": progress["unavailable"],
        }
        metrics.details["table"] = {
            "rows": [
                {
                    "key": s,
                    "count": after_dist.get(s, 0),
                    "delta": after_dist.get(s, 0) - before_dist.get(s, 0),
                }
                for s in statuses
            ]
        }
        return metrics

    step(logger, "Vérification du statut open access sur Unpaywall")
    if not total:
        nothing_to_do(logger)
        return _result()

    logger.info(
        "%s%s %s ou %s depuis plus de %s",
        BRANCH,
        quantity(stale_total, "DOI", "DOI"),
        inflect(stale_total, "jamais vérifié"),
        inflect(stale_total, "vérifié"),
        quantity(staleness_days, "jour"),
    )
    if max_per_run and max_per_run < stale_total:
        deferred = stale_total - total
        logger.info(
            "%splafond de %s par run ⇒ %s %s au prochain",
            BRANCH,
            max_per_run,
            deferred,
            inflect(deferred, "reporté"),
        )

    sem = asyncio.Semaphore(max_concurrent)

    async with httpx2.AsyncClient(verify=tls_context()) as client:

        async def fetch(doi: str) -> tuple[str, LookupOutcome[str]]:
            async with sem:
                return doi, await fetcher(client, doi)

        # Par paquets : les requêtes d'un paquet partent en concurrence (débit borné par `sem`), puis ses écritures sont committées.
        with track_progress(total, BRANCH.rstrip(), logger) as bar:
            for start in range(0, total, BATCH_SIZE):
                chunk = dois[start : start + BATCH_SIZE]
                verdicts: list[tuple[str, str | None]] = []
                for doi, outcome in await asyncio.gather(*(fetch(doi) for doi in chunk)):
                    # Unpaywall indisponible : rien n'est écrit, le DOI reste dans la file.
                    if isinstance(outcome, Unavailable):
                        progress["unavailable"] += 1
                    elif isinstance(outcome, NotFound):
                        verdicts.append((doi, None))
                    else:
                        verdicts.append((doi, outcome))
                await asyncio.to_thread(_apply_verdicts, store, verdicts, progress)
                await asyncio.to_thread(conn.commit)
                bar.advance(len(chunk))

    summary = [
        quantity(progress["new"], "nouveau", "nouveaux"),
        quantity(progress["updated"], "modifié"),
        quantity(progress["unchanged"], "inchangé"),
        quantity(progress["not_found"], "non trouvé", "non trouvés"),
    ]
    if progress["unavailable"]:
        summary.append(quantity(progress["unavailable"], "reporté"))
    logger.info("%s%s", LAST_BRANCH, ", ".join(summary))

    return _result()


def _apply_verdicts(
    store: OaStatusStore,
    verdicts: list[tuple[str, str | None]],
    progress: dict[str, int],
) -> None:
    """Classe les verdicts face à ceux en table, les écrit, puis recalcule le statut OA des publications de ces DOI (`publication_oa_status`)."""
    by_doi = dict(verdicts)
    stored = store.fetch_verdicts(list(by_doi))
    for doi, status in verdicts:
        if status is None:
            progress["not_found"] += 1
        elif doi not in stored:
            progress["new"] += 1
        elif stored[doi] != status:
            progress["updated"] += 1
        else:
            progress["unchanged"] += 1
    store.record_verdicts(verdicts)
    for publication in store.fetch_oa_inputs(list(by_doi)):
        status = publication_oa_status(publication.signals, by_doi.get(publication.doi))
        if status != publication.oa_status:
            store.update_oa_status(publication.id, status)


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    base_url = API_BASE_URLS["unpaywall"]
    email = get_polite_pool_email_optional() or ""

    async def fetcher(client: httpx2.AsyncClient, doi: str) -> LookupOutcome[str]:
        return await fetch_oa_status(client, doi, base_url=base_url, email=email)

    return SingleTaskPhase(
        "oa_status.verify_unpaywall",
        OaStatusPhase(
            fetcher,
            staleness_days=lambda conn: delay(conn, ConfigKey.UNPAYWALL_RECHECK_AFTER_DAYS),
            max_per_run=lambda conn: cap(conn, ConfigKey.UNPAYWALL_MAX_PER_RUN),
        ),
    )
