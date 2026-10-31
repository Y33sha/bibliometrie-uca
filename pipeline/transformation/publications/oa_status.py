"""Phase `oa_status` : verdicts d'Unpaywall sur les DOI des publications (`sources.unpaywall`), et statut open access dérivé (`publications.oa_status`).

Unpaywall est interrogé pour les DOI jamais vérifiés ou périmés, hors DOI DataCite, et chaque verdict est écrit. Un DOI absent d'Unpaywall reçoit un verdict nul. Quand Unpaywall est indisponible, le DOI est reporté au run suivant. Le statut des publications de ces DOI est ensuite recalculé par `publication_oa_status`, à partir de leurs copies, des statuts déclarés par leurs enregistrements sources, de leur revue et du verdict.

Le délai de péremption et le plafond par run bornent la phase. Les DOI jamais vérifiés au-delà du plafond sont traités aux runs suivants. L'accès à Unpaywall exige l'adresse du polite pool.
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
from domain.publications.access import Copy
from domain.publications.metadata import OaStatus
from domain.publications.open_access import publication_oa_status
from infrastructure.db.scalars import scalar_int
from infrastructure.read_models.publications.copies import publication_copies
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
"""Interrogation d'Unpaywall : `(client, doi) → statut OA, NotFound ou Unavailable`."""

BATCH_SIZE = 50
# Requêtes simultanées, sous le débit recommandé par Unpaywall (10 par seconde).
MAX_CONCURRENT = 5


class OaSignal(NamedTuple):
    """Source et statut OA d'un enregistrement source d'une publication."""

    source: str
    oa_status: str | None


class PublicationOaInputs(NamedTuple):
    """Données du calcul du statut OA d'une publication : son DOI, son statut courant, sa revue, les statuts déclarés par ses enregistrements sources, ses copies."""

    id: int
    doi: str | None
    oa_status: str | None
    has_serial: bool
    serial_oa_model: str | None
    signals: list[OaSignal]
    copies: list[Copy]


# DOI des publications sans verdict d'Unpaywall, ou à verdict de plus de `:stale` jours. Les DOI DataCite sont absents d'Unpaywall, donc écartés.
_STALE_DOIS = """
    SELECT d.doi, u.checked_at
    FROM (SELECT DISTINCT lower(doi) AS doi FROM publications WHERE doi IS NOT NULL) d
    LEFT JOIN unpaywall u ON u.doi = d.doi
    LEFT JOIN doi_prefixes dp ON dp.prefix = split_part(d.doi, '/', 1)
    WHERE (u.doi IS NULL OR u.checked_at < now() - make_interval(days => :stale))
      AND dp.ra IS DISTINCT FROM 'DataCite'
"""


class OaStatusStore:
    """DOI à vérifier sur Unpaywall, verdicts reçus, statut OA des publications."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def fetch_dois_to_check(self, *, limit: int | None = None, staleness_days: int) -> list[str]:
        """Renvoie les DOI à vérifier sur Unpaywall : jamais vérifiés d'abord, puis les plus périmés.

        Args:
            limit: plafond du run.
        """
        rows = self._conn.execute(
            text(f"{_STALE_DOIS} ORDER BY checked_at ASC NULLS FIRST, doi LIMIT :lim"),
            {"stale": staleness_days, "lim": limit},
        )
        return [r.doi for r in rows]

    def count_dois_to_check(self, *, staleness_days: int) -> int:
        """Compte les DOI à vérifier, sans plafond."""
        return scalar_int(
            self._conn.execute(
                text(f"SELECT count(*) FROM ({_STALE_DOIS}) s"), {"stale": staleness_days}
            )
        )

    def fetch_verdicts(self, dois: Sequence[str]) -> dict[str, str | None]:
        """Renvoie le verdict en table de chacun de ces DOI, quand il en a un."""
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
        """Renvoie les publications de ces DOI, avec leur revue, les statuts OA de leurs enregistrements sources et leurs copies."""
        return self._fetch_oa_inputs("lower(p.doi) = ANY(:keys)", list(dois))

    def fetch_oa_inputs_of(self, publication_ids: Sequence[int]) -> list[PublicationOaInputs]:
        """Renvoie ces publications, avec leur revue, les statuts OA de leurs enregistrements sources et leurs copies."""
        return self._fetch_oa_inputs("p.id = ANY(:keys)", list(publication_ids))

    def _fetch_oa_inputs(
        self, where: str, keys: list[str] | list[int]
    ) -> list[PublicationOaInputs]:
        rows = self._conn.execute(
            text(f"""
                SELECT p.id, lower(p.doi) AS doi, p.oa_status::text AS oa_status,
                       p.serial_id IS NOT NULL AS has_serial, s.oa_model::text AS oa_model,
                       array_agg(sr.source::text ORDER BY sr.id) AS sources,
                       array_agg(sr.oa_status::text ORDER BY sr.id) AS statuses
                FROM publications p
                JOIN source_records sr ON sr.publication_id = p.id
                LEFT JOIN serials s ON s.id = p.serial_id
                WHERE {where}
                GROUP BY p.id, s.oa_model
            """),  # noqa: S608 — condition choisie par le code
            {"keys": keys},
        ).all()
        copies = publication_copies(self._conn, [r.id for r in rows])
        return [
            PublicationOaInputs(
                r.id,
                r.doi,
                r.oa_status,
                r.has_serial,
                r.oa_model,
                [OaSignal(s, o) for s, o in zip(r.sources, r.statuses, strict=True)],
                copies.get(r.id, []),
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
        """Compte les publications par statut OA (`oa_status` → nombre)."""
        rows = self._conn.execute(
            text(
                f"SELECT COALESCE(oa_status::text, '{OaStatus.UNKNOWN.value}') AS status, count(*) AS n "
                f"FROM publications GROUP BY COALESCE(oa_status::text, '{OaStatus.UNKNOWN.value}')"
            )
        ).all()
        return {r.status: int(r.n) for r in rows}


@dataclass(frozen=True)
class OaStatusPhase:
    """Vérification sur Unpaywall du statut OA des publications à DOI."""

    fetcher: OaStatusFetcher
    staleness_days: Callable[[Connection], int]
    """Lit le délai, en jours, au-delà duquel un DOI vérifié l'est de nouveau."""
    max_per_run: Callable[[Connection], int | None]
    """Lit le plafond de DOI vérifiés par run ; `None` vaut illimité."""
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
    """Interroge Unpaywall pour les DOI à vérifier, écrit les verdicts, recalcule le statut OA des publications de ces DOI, puis renvoie les métriques du run."""
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
    """Classe les verdicts par rapport à ceux en table, les écrit, puis recalcule le statut OA des publications de ces DOI (`publication_oa_status`)."""
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
        status = publication_oa_status(
            publication.copies,
            publication.signals,
            unpaywall=by_doi.get(publication.doi) if publication.doi else None,
            has_serial=publication.has_serial,
            serial_oa_model=publication.serial_oa_model,
        )
        if status != publication.oa_status:
            store.update_oa_status(publication.id, status)


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
