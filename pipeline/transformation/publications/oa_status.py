"""Phase `oa_status` : réponses des services externes sur les DOI des enregistrements sources (`sources.dois`).

Les DOI interrogés sont les DOI candidats au DOI d'une publication (`_CANDIDATE_DOIS`). Deux tâches interrogent chacune un service sur ces DOI, jamais interrogés ou périmés, et écrivent chaque réponse :

- `oa_status.resolve_dois` lit chez doi.org l'URL de résolution de chaque DOI. Un DOI inconnu de doi.org reçoit une URL nulle.
- `oa_status.verify_unpaywall` demande à Unpaywall le statut open access de chaque DOI, hors DOI DataCite. Un DOI absent d'Unpaywall reçoit un verdict nul.

Quand le service est indisponible, le DOI est reporté au run suivant. Les publications d'un DOI dont la réponse change entrent dans la file `publications_queue` : leur consolidation recalcule leur statut open access.

Un délai de péremption et un plafond par run bornent chaque tâche. Les DOI au-delà du plafond sont traités aux runs suivants. L'accès à Unpaywall exige l'adresse du polite pool.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple, cast

import httpx2
from sqlalchemy import Connection, text

from domain.config import ConfigKey
from domain.sources import registry
from infrastructure.db.queues import Queue, enqueue
from infrastructure.db.scalars import scalar_int
from pipeline.graph import Task
from pipeline.http.lookup import LookupOutcome, NotFound, Unavailable
from pipeline.http.polite_pool import default_user_agent, get_polite_pool_email_optional
from pipeline.http.tls import tls_context
from pipeline.ingestion.api_params import API_BASE_URLS, MAX_CONCURRENT
from pipeline.ingestion.complements.doi_org import fetch_registered_url
from pipeline.ingestion.complements.unpaywall import fetch_oa_status
from pipeline.runtime.config import cap, delay
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import (
    BRANCH,
    LAST_BRANCH,
    inflect,
    nothing_to_do,
    quantity,
)
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress

type DoiFetcher = Callable[[httpx2.AsyncClient, str], Awaitable[LookupOutcome[str]]]
"""Interrogation d'un service sur un DOI : `(client, doi) → réponse, NotFound ou Unavailable`."""

BATCH_SIZE = 50


class DoiService(NamedTuple):
    """Service externe interrogé sur les DOI, et colonnes de `dois` gardant sa réponse."""

    answer_column: str
    answer_type: str
    date_column: str
    skips_datacite: bool
    """Les DOI DataCite sont absents du service, donc écartés."""


UNPAYWALL = DoiService("unpaywall_oa_status", "oa_type", "unpaywall_checked_at", True)
DOI_ORG = DoiService("registered_url", "text", "resolved_at", False)


_LOOKUP = "lookup"
"""Clé du bilan de la tâche dans `details` : DOI à interroger, interrogés, et réponses par issue."""

_CANDIDATE_DOIS = """
    SELECT DISTINCT d.doi
    FROM (
        SELECT sri.id_value AS doi, sri.role, sri.source_record_id,
               count(*) OVER (PARTITION BY sri.source_record_id) AS record_dois
        FROM source_record_identifiers sri
        WHERE sri.id_type = 'doi' AND sri.removed_by IS NULL
    ) d
    JOIN source_records sr ON sr.id = d.source_record_id
    WHERE (d.role IN ('primary', 'derived') OR d.record_dois = 1)
      AND (sr.publication_id IS NOT NULL
           OR EXISTS (SELECT 1 FROM source_contributions sc
                      WHERE sc.source_record_id = sr.id AND sc.in_perimeter))
      AND NOT EXISTS (SELECT 1 FROM doi_targets t WHERE t.doi = d.doi)
"""
"""DOI candidats au DOI d'une publication, selon la règle des ancres (`domain.source_records.keys.doi_anchors`) : DOI actifs de rôle `primary` ou `derived`, ou seul DOI actif de leur enregistrement source. L'enregistrement source est rattaché à une publication ou doté d'une contribution source du périmètre. Les DOI qui ont une cible sont écartés."""


def _stale_dois(service: DoiService) -> str:
    """Renvoie la requête des DOI candidats sans réponse du service, ou à réponse de plus de `:stale` jours."""
    datacite = (
        """
        LEFT JOIN doi_prefixes dp ON dp.prefix = split_part(d.doi, '/', 1)
        WHERE dp.ra IS DISTINCT FROM 'DataCite' AND
        """
        if service.skips_datacite
        else "WHERE"
    )
    return f"""
        SELECT d.doi, x.{service.date_column} AS answered_at
        FROM ({_CANDIDATE_DOIS}) d
        LEFT JOIN dois x ON x.doi = d.doi
        {datacite} (x.{service.date_column} IS NULL
                    OR x.{service.date_column} < now() - make_interval(days => :stale))
    """  # noqa: S608 — colonnes choisies par le code


class OaStatusStore:
    """DOI à interroger, réponses reçues, publications à recalculer."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def fetch_dois_to_query(
        self, service: DoiService, *, limit: int | None = None, staleness_days: int
    ) -> list[str]:
        """Renvoie les DOI à soumettre au service : jamais interrogés d'abord, puis les plus périmés.

        Args:
            limit: plafond du run.
        """
        rows = self._conn.execute(
            text(f"{_stale_dois(service)} ORDER BY answered_at ASC NULLS FIRST, doi LIMIT :lim"),
            {"stale": staleness_days, "lim": limit},
        )
        return [r.doi for r in rows]

    def count_dois_to_query(self, service: DoiService, *, staleness_days: int) -> int:
        """Compte les DOI à soumettre au service, sans plafond."""
        return scalar_int(
            self._conn.execute(
                text(f"SELECT count(*) FROM ({_stale_dois(service)}) s"),
                {"stale": staleness_days},
            )
        )

    def fetch_answers(self, service: DoiService, dois: Sequence[str]) -> dict[str, str | None]:
        """Renvoie la réponse en table du service pour chacun de ces DOI, quand il en a une."""
        rows = self._conn.execute(
            text(f"""
                SELECT doi, {service.answer_column}::text AS answer FROM dois
                WHERE doi = ANY(:dois) AND {service.date_column} IS NOT NULL
            """),  # noqa: S608 — colonnes choisies par le code
            {"dois": list(dois)},
        )
        return {r.doi: r.answer for r in rows}

    def record_answers(
        self, service: DoiService, answers: Sequence[tuple[str, str | None]]
    ) -> None:
        """Écrit la réponse du service pour chaque DOI, `None` pour un DOI inconnu du service, datée de l'instant."""
        if not answers:
            return
        answer, date = service.answer_column, service.date_column
        self._conn.execute(
            text(f"""
                INSERT INTO dois (doi, {answer}, {date})
                SELECT v.doi, CAST(v.answer AS {service.answer_type}), now()
                FROM unnest(CAST(:dois AS text[]), CAST(:answers AS text[])) AS v(doi, answer)
                ON CONFLICT (doi) DO UPDATE
                SET {answer} = EXCLUDED.{answer}, {date} = EXCLUDED.{date}
            """),  # noqa: S608 — colonnes choisies par le code
            {"dois": [d for d, _ in answers], "answers": [a for _, a in answers]},
        )

    def enqueue_publications(self, dois: Sequence[str]) -> int:
        """Met en file de consolidation les publications de ces DOI. Renvoie le nombre de publications mises en file."""
        return enqueue(
            self._conn,
            Queue.PUBLICATIONS,
            "SELECT id FROM publications WHERE doi = ANY(:dois)",
            {"dois": list(dois)},
        )


@dataclass(frozen=True)
class DoiLookupTask:
    """Tâche interrogeant un service sur les DOI des publications."""

    service: DoiService
    fetcher: DoiFetcher
    participle: str
    """Participe passé de l'interrogation, au masculin singulier (« vérifié »)."""
    not_found: tuple[str, str]
    """Libellé d'un DOI inconnu du service, au singulier et au pluriel."""
    staleness_days: Callable[[Connection], int]
    """Lit le délai, en jours, au-delà duquel un DOI interrogé l'est de nouveau."""
    max_per_run: Callable[[Connection], int | None]
    """Lit le plafond de DOI interrogés par run ; `None` vaut illimité."""
    max_concurrent: int
    """Requêtes simultanées."""
    store_factory: Callable[[Connection], OaStatusStore] = OaStatusStore

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Interroge le service dans une seule transaction, avec un commit par paquet."""
        with ctx.open_tx() as conn:
            return asyncio.run(
                _look_up(
                    conn,
                    self.store_factory(conn),
                    ctx.logger,
                    self,
                    staleness_days=self.staleness_days(conn),
                    max_per_run=self.max_per_run(conn),
                )
            )


async def _look_up(
    conn: Connection,
    store: OaStatusStore,
    logger: logging.Logger,
    task: DoiLookupTask,
    *,
    staleness_days: int,
    max_per_run: int | None,
) -> PhaseMetrics:
    """Interroge le service pour les DOI à interroger, écrit les réponses, met en file de consolidation les publications des DOI dont la réponse change, puis renvoie les métriques du run, avec son bilan dans `details`."""
    dois = store.fetch_dois_to_query(task.service, limit=max_per_run, staleness_days=staleness_days)
    stale_total = store.count_dois_to_query(task.service, staleness_days=staleness_days)
    counts: Counter[str] = Counter()
    if dois:
        await _query_service(
            conn,
            store,
            logger,
            task,
            dois,
            counts,
            stale_total=stale_total,
            staleness_days=staleness_days,
            max_per_run=max_per_run,
        )
    else:
        nothing_to_do(logger)

    metrics = PhaseMetrics()
    metrics.add(
        seen=len(dois),
        new=counts["new"],
        updated=counts["updated"],
        unchanged=counts["unchanged"],
        not_found=counts["not_found"],
        errors=counts["unavailable"],
    )
    metrics.details[_LOOKUP] = {
        "stale": stale_total,
        "checked": len(dois),
        **{key: counts[key] for key in _OUTCOMES},
    }
    return metrics


_OUTCOMES = ("new", "updated", "unchanged", "not_found", "unavailable")
"""Issues d'une interrogation : réponse nouvelle, modifiée, inchangée, DOI inconnu du service, service indisponible."""


async def _query_service(
    conn: Connection,
    store: OaStatusStore,
    logger: logging.Logger,
    task: DoiLookupTask,
    dois: list[str],
    counts: Counter[str],
    *,
    stale_total: int,
    staleness_days: int,
    max_per_run: int | None,
) -> None:
    """Interroge le service sur `dois`, par paquets, et écrit les réponses de chaque paquet avec un commit. Compte les issues dans `counts`."""
    total = len(dois)
    logger.info(
        "%s%s %s ou %s depuis plus de %s",
        BRANCH,
        quantity(stale_total, "DOI", "DOI"),
        inflect(stale_total, f"jamais {task.participle}"),
        inflect(stale_total, task.participle),
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

    sem = asyncio.Semaphore(task.max_concurrent)

    async with httpx2.AsyncClient(verify=tls_context()) as client:

        async def fetch(doi: str) -> tuple[str, LookupOutcome[str]]:
            async with sem:
                return doi, await task.fetcher(client, doi)

        # Par paquets : les requêtes d'un paquet partent en concurrence (débit borné par `sem`), puis ses écritures sont committées.
        with track_progress(total, BRANCH.rstrip(), logger) as bar:
            for start in range(0, total, BATCH_SIZE):
                chunk = dois[start : start + BATCH_SIZE]
                answers: list[tuple[str, str | None]] = []
                for doi, outcome in await asyncio.gather(*(fetch(doi) for doi in chunk)):
                    # Service indisponible : rien n'est écrit, le DOI reste dans la file.
                    if isinstance(outcome, Unavailable):
                        counts["unavailable"] += 1
                    elif isinstance(outcome, NotFound):
                        answers.append((doi, None))
                    else:
                        answers.append((doi, outcome))
                await asyncio.to_thread(_apply_answers, store, task.service, answers, counts)
                await asyncio.to_thread(conn.commit)
                bar.advance(len(chunk))

    summary = [
        quantity(counts["new"], "nouveau", "nouveaux"),
        quantity(counts["updated"], "modifié"),
        quantity(counts["unchanged"], "inchangé"),
        quantity(counts["not_found"], *task.not_found),
    ]
    if counts["unavailable"]:
        summary.append(quantity(counts["unavailable"], "reporté"))
    summary.append(
        quantity(counts["queued"], "publication à recalculer", "publications à recalculer")
    )
    logger.info("%s%s", LAST_BRANCH, ", ".join(summary))


def _apply_answers(
    store: OaStatusStore,
    service: DoiService,
    answers: list[tuple[str, str | None]],
    counts: Counter[str],
) -> None:
    """Classe les réponses par rapport à celles en table, les écrit, puis met en file de consolidation les publications des DOI dont la réponse change."""
    stored = store.fetch_answers(service, [doi for doi, _ in answers])
    for doi, answer in answers:
        if answer is None:
            counts["not_found"] += 1
        elif doi not in stored:
            counts["new"] += 1
        elif stored[doi] != answer:
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
    store.record_answers(service, answers)
    changed = [doi for doi, answer in answers if doi not in stored or stored[doi] != answer]
    if changed:
        counts["queued"] += store.enqueue_publications(changed)


_LOOKUP_READS = (
    "source_record_identifiers",
    "source_records.publication_id",
    "source_contributions.in_perimeter",
    "doi_targets",
    "dois.doi",
    # Publications des DOI dont la réponse change.
    "publications.doi",
    "config",
)
"""Lectures d'une tâche de la phase `oa_status` : DOI candidats, DOI en table, publications à mettre en file."""

_LOOKUP_PREVIOUS_RUN = (
    "source_records.publication_id",
    "source_record_identifiers.removed_by",
    "publications.doi",
    "dois.doi",
)
"""Rattachements, DOI retirés et DOI des publications, écrits par la réconciliation et la purge des publications ; lignes de `dois` créées par l'autre service."""


def _resolve_dois(ctx: PhaseContext) -> PhaseMetrics:
    # L'API des handles de doi.org est publique : l'adresse du polite pool y est facultative.
    user_agent = default_user_agent()

    async def fetcher(client: httpx2.AsyncClient, doi: str) -> LookupOutcome[str]:
        return await fetch_registered_url(client, doi, user_agent=user_agent)

    return DoiLookupTask(
        DOI_ORG,
        fetcher,
        participle="lu",
        not_found=("inconnu de doi.org", "inconnus de doi.org"),
        staleness_days=lambda conn: delay(conn, ConfigKey.DOI_RESOLUTION_RECHECK_AFTER_DAYS),
        max_per_run=lambda conn: cap(conn, ConfigKey.DOI_RESOLUTION_MAX_PER_RUN),
        max_concurrent=MAX_CONCURRENT["doi_org"],
    ).run(ctx)


def _verify_unpaywall(ctx: PhaseContext) -> PhaseMetrics:
    base_url = API_BASE_URLS["unpaywall"]
    email = get_polite_pool_email_optional() or ""

    async def fetcher(client: httpx2.AsyncClient, doi: str) -> LookupOutcome[str]:
        return await fetch_oa_status(client, doi, base_url=base_url, email=email)

    return DoiLookupTask(
        UNPAYWALL,
        fetcher,
        participle="vérifié",
        not_found=("non trouvé", "non trouvés"),
        staleness_days=lambda conn: delay(conn, ConfigKey.UNPAYWALL_RECHECK_AFTER_DAYS),
        max_per_run=lambda conn: cap(conn, ConfigKey.UNPAYWALL_MAX_PER_RUN),
        max_concurrent=MAX_CONCURRENT["unpaywall"],
    ).run(ctx)


TASKS = (
    Task(
        "resolve_dois",
        reads=(*_LOOKUP_READS, "dois.registered_url", "dois.resolved_at"),
        writes=("dois.doi", "dois.registered_url", "dois.resolved_at", "publications_queue"),
        previous_run=_LOOKUP_PREVIOUS_RUN,
        network=registry.DOI_ORG,
        run=_resolve_dois,
        section="URL de résolution des DOI sur doi.org",
    ),
    Task(
        "verify_unpaywall",
        reads=(
            *_LOOKUP_READS,
            "dois.unpaywall_oa_status",
            "dois.unpaywall_checked_at",
            "doi_prefixes.ra",
        ),
        writes=(
            "dois.doi",
            "dois.unpaywall_oa_status",
            "dois.unpaywall_checked_at",
            "publications_queue",
        ),
        previous_run=_LOOKUP_PREVIOUS_RUN,
        network="unpaywall",
        run=_verify_unpaywall,
        section="Vérification du statut open access sur Unpaywall",
    ),
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie la somme des métriques des tâches, avec une ligne par service interrogé (`services`)."""
    metrics = PhaseMetrics()
    lookups: dict[str, Mapping[str, int]] = {}
    for name, task_metrics in by_task.items():
        metrics.merge(task_metrics)
        if (lookup := metrics.details.pop(_LOOKUP, None)) is not None:
            lookups[name] = cast("Mapping[str, int]", lookup)
    if lookups:
        metrics.details["services"] = {
            "rows": [{"key": name, **counts} for name, counts in lookups.items()]
        }
    return metrics
