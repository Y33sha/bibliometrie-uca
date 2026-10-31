"""Phase `oa_status` : réponses des services externes sur les DOI des publications (`sources.dois`), et statut open access dérivé (`publications.oa_status`).

Deux tâches interrogent chacune un service sur les DOI jamais interrogés ou périmés, et écrivent chaque réponse :

- `oa_status.resolve_dois` lit chez doi.org l'URL de résolution de chaque DOI. Un DOI inconnu de doi.org reçoit une URL nulle.
- `oa_status.verify_unpaywall` demande à Unpaywall le statut open access de chaque DOI, hors DOI DataCite. Un DOI absent d'Unpaywall reçoit un verdict nul.

Quand le service est indisponible, le DOI est reporté au run suivant. Le statut des publications des DOI interrogés est ensuite recalculé par `publication_oa_status`, à partir de leurs copies, de leurs embargos, de leur type, de leur revue et du verdict d'Unpaywall.

Un délai de péremption et un plafond par run bornent chaque tâche. Les DOI au-delà du plafond sont traités aux runs suivants. L'accès à Unpaywall exige l'adresse du polite pool.
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
from domain.publications.open_access import is_restricted, publication_oa_status
from infrastructure.db.scalars import scalar_int
from infrastructure.read_models.publications.copies import publication_copies
from infrastructure.sql_fragments import under_active_embargo
from pipeline.http.lookup import LookupOutcome, NotFound, Unavailable
from pipeline.http.polite_pool import default_user_agent, get_polite_pool_email_optional
from pipeline.http.tls import tls_context
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.complements.doi_org import fetch_registered_url
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
from pipeline.task_runner import TaskStep, run_tasks

type DoiFetcher = Callable[[httpx2.AsyncClient, str], Awaitable[LookupOutcome[str]]]
"""Interrogation d'un service sur un DOI : `(client, doi) → réponse, NotFound ou Unavailable`."""

BATCH_SIZE = 50
# Requêtes simultanées, sous le débit recommandé par Unpaywall (10 par seconde).
MAX_CONCURRENT = 5

RESOLVE_TASK = "oa_status.resolve_dois"
UNPAYWALL_TASK = "oa_status.verify_unpaywall"


class DoiService(NamedTuple):
    """Service externe interrogé sur les DOI des publications, et colonnes de `dois` gardant sa réponse."""

    answer_column: str
    answer_type: str
    date_column: str
    skips_datacite: bool
    """Les DOI DataCite sont absents du service, donc écartés."""


UNPAYWALL = DoiService("unpaywall_oa_status", "oa_type", "unpaywall_checked_at", True)
DOI_ORG = DoiService("registered_url", "text", "resolved_at", False)


class PublicationOaInputs(NamedTuple):
    """Données du calcul du statut OA d'une publication."""

    id: int
    doi: str | None
    oa_status: str | None
    has_serial: bool
    serial_oa_model: str | None
    embargoed: bool
    """Un enregistrement source de la publication est sous embargo actif."""
    restricted: bool
    """La publication est fermée par nature (`is_restricted`)."""
    unpaywall: str | None
    """Verdict d'Unpaywall sur le DOI de la publication, `None` sans verdict."""
    copies: list[Copy]

    def computed_status(self) -> OaStatus:
        """Renvoie le statut OA déduit de ces données (`publication_oa_status`)."""
        return publication_oa_status(
            self.copies,
            embargoed=self.embargoed,
            restricted=self.restricted,
            unpaywall=self.unpaywall,
            has_serial=self.has_serial,
            serial_oa_model=self.serial_oa_model,
        )


def _stale_dois(service: DoiService) -> str:
    """Renvoie la requête des DOI de publication sans réponse du service, ou à réponse de plus de `:stale` jours."""
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
        FROM (SELECT DISTINCT lower(doi) AS doi FROM publications WHERE doi IS NOT NULL) d
        LEFT JOIN dois x ON x.doi = d.doi
        {datacite} (x.{service.date_column} IS NULL
                    OR x.{service.date_column} < now() - make_interval(days => :stale))
    """  # noqa: S608 — colonnes choisies par le code


class OaStatusStore:
    """DOI à interroger, réponses reçues, statut OA des publications."""

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

    def fetch_oa_inputs(self, dois: Sequence[str]) -> list[PublicationOaInputs]:
        """Renvoie les publications de ces DOI, avec les données du calcul de leur statut OA."""
        return self._fetch_oa_inputs("lower(p.doi) = ANY(:keys)", list(dois))

    def fetch_oa_inputs_of(self, publication_ids: Sequence[int]) -> list[PublicationOaInputs]:
        """Renvoie ces publications, avec les données du calcul de leur statut OA."""
        return self._fetch_oa_inputs("p.id = ANY(:keys)", list(publication_ids))

    def _fetch_oa_inputs(
        self, where: str, keys: list[str] | list[int]
    ) -> list[PublicationOaInputs]:
        rows = self._conn.execute(
            text(f"""
                SELECT p.id, lower(p.doi) AS doi, p.oa_status::text AS oa_status,
                       p.serial_id IS NOT NULL AS has_serial, s.oa_model::text AS oa_model,
                       p.doc_type::text AS doc_type, p.source_extras,
                       bool_or({under_active_embargo("sr")}) AS embargoed,
                       d.unpaywall_oa_status::text AS unpaywall
                FROM publications p
                JOIN source_records sr ON sr.publication_id = p.id
                LEFT JOIN serials s ON s.id = p.serial_id
                LEFT JOIN dois d ON d.doi = lower(p.doi)
                WHERE {where}
                GROUP BY p.id, s.oa_model, d.unpaywall_oa_status
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
                r.embargoed,
                is_restricted(r.doc_type, r.source_extras),
                r.unpaywall,
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
class DoiLookupTask:
    """Tâche interrogeant un service sur les DOI des publications."""

    service: DoiService
    fetcher: DoiFetcher
    title: str
    """Titre de la sous-étape dans le journal."""
    participle: str
    """Participe passé de l'interrogation, au masculin singulier (« vérifié »)."""
    not_found: tuple[str, str]
    """Libellé d'un DOI inconnu du service, au singulier et au pluriel."""
    staleness_days: Callable[[Connection], int]
    """Lit le délai, en jours, au-delà duquel un DOI interrogé l'est de nouveau."""
    max_per_run: Callable[[Connection], int | None]
    """Lit le plafond de DOI interrogés par run ; `None` vaut illimité."""
    max_concurrent: int = MAX_CONCURRENT
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
    """Interroge le service pour les DOI à interroger, écrit les réponses, recalcule le statut OA des publications de ces DOI, puis renvoie les métriques du run."""
    metrics = PhaseMetrics()
    dois = store.fetch_dois_to_query(task.service, limit=max_per_run, staleness_days=staleness_days)
    total = len(dois)
    stale_total = store.count_dois_to_query(task.service, staleness_days=staleness_days)
    before_dist = store.count_publications_by_oa_status()

    progress = {"new": 0, "updated": 0, "unchanged": 0, "not_found": 0, "unavailable": 0}

    def _result() -> PhaseMetrics:
        # Indicateurs : réponses du run (nouvelles, modifiées, inchangées, non trouvées), puis répartition des publications par statut OA avec le delta du run (avant → après).
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

    step(logger, task.title)
    if not total:
        nothing_to_do(logger)
        return _result()

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
                        progress["unavailable"] += 1
                    elif isinstance(outcome, NotFound):
                        answers.append((doi, None))
                    else:
                        answers.append((doi, outcome))
                await asyncio.to_thread(_apply_answers, store, task.service, answers, progress)
                await asyncio.to_thread(conn.commit)
                bar.advance(len(chunk))

    summary = [
        quantity(progress["new"], "nouveau", "nouveaux"),
        quantity(progress["updated"], "modifié"),
        quantity(progress["unchanged"], "inchangé"),
        quantity(progress["not_found"], *task.not_found),
    ]
    if progress["unavailable"]:
        summary.append(quantity(progress["unavailable"], "reporté"))
    logger.info("%s%s", LAST_BRANCH, ", ".join(summary))

    return _result()


def _apply_answers(
    store: OaStatusStore,
    service: DoiService,
    answers: list[tuple[str, str | None]],
    progress: dict[str, int],
) -> None:
    """Classe les réponses par rapport à celles en table, les écrit, puis recalcule le statut OA des publications de ces DOI."""
    stored = store.fetch_answers(service, [doi for doi, _ in answers])
    for doi, answer in answers:
        if answer is None:
            progress["not_found"] += 1
        elif doi not in stored:
            progress["new"] += 1
        elif stored[doi] != answer:
            progress["updated"] += 1
        else:
            progress["unchanged"] += 1
    store.record_answers(service, answers)
    for publication in store.fetch_oa_inputs([doi for doi, _ in answers]):
        status = publication.computed_status()
        if status != publication.oa_status:
            store.update_oa_status(publication.id, status)


@dataclass(frozen=True)
class OaStatusPhase:
    """Phase `oa_status` : lecture des URL de résolution, puis vérification sur Unpaywall."""

    resolution: DoiLookupTask
    unpaywall: DoiLookupTask

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute les deux tâches et renvoie les métriques de la vérification sur Unpaywall."""
        by_task = run_tasks(
            "oa_status",
            {
                RESOLVE_TASK: TaskStep(self.resolution.run),
                UNPAYWALL_TASK: TaskStep(self.unpaywall.run),
            },
            ctx,
        )
        return by_task[UNPAYWALL_TASK]


def build() -> Phase:
    base_url = API_BASE_URLS["unpaywall"]
    email = get_polite_pool_email_optional() or ""
    # L'API des handles de doi.org est publique : l'adresse du polite pool y est facultative.
    user_agent = default_user_agent()

    async def unpaywall_fetcher(client: httpx2.AsyncClient, doi: str) -> LookupOutcome[str]:
        return await fetch_oa_status(client, doi, base_url=base_url, email=email)

    async def doi_org_fetcher(client: httpx2.AsyncClient, doi: str) -> LookupOutcome[str]:
        return await fetch_registered_url(client, doi, user_agent=user_agent)

    return OaStatusPhase(
        resolution=DoiLookupTask(
            DOI_ORG,
            doi_org_fetcher,
            title="URL de résolution des DOI sur doi.org",
            participle="lu",
            not_found=("inconnu de doi.org", "inconnus de doi.org"),
            staleness_days=lambda conn: delay(conn, ConfigKey.DOI_RESOLUTION_RECHECK_AFTER_DAYS),
            max_per_run=lambda conn: cap(conn, ConfigKey.DOI_RESOLUTION_MAX_PER_RUN),
        ),
        unpaywall=DoiLookupTask(
            UNPAYWALL,
            unpaywall_fetcher,
            title="Vérification du statut open access sur Unpaywall",
            participle="vérifié",
            not_found=("non trouvé", "non trouvés"),
            staleness_days=lambda conn: delay(conn, ConfigKey.UNPAYWALL_RECHECK_AFTER_DAYS),
            max_per_run=lambda conn: cap(conn, ConfigKey.UNPAYWALL_MAX_PER_RUN),
        ),
    )
