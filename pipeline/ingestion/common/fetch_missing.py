"""Phase `fetch_missing` : rattrapage des documents repérés dans une source mais absents d'une autre. Deux mécanismes, dans cet ordre :

1. **Recherche dans HAL** (`pipeline.ingestion.hal.fetch_missing`) : par hal-id (repéré dans OpenAlex et ScanR), puis par NNT (thèses sans document HAL).
2. **Recherche dans theses.fr** (`pipeline.ingestion.theses.fetch_missing`) : par NNT repéré dans une autre source.
3. **Recherche par DOI** : pour chaque source cible, les DOI vus ailleurs et absents de la cible. Les tâches `fetch_missing.doi.<source>` forment un groupe parallèle.

Un identifiant cherché en vain est inscrit dans `failed_lookups` (`pipeline.ingestion.common.failed_lookups`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Protocol

import httpx2
from sqlalchemy import Connection, ScalarResult, text

from domain.publications.identifiers import clean_doi
from domain.source_publications.external_ids import ExternalIdType
from domain.sources.registry import (
    ALL_SOURCES_SET as VALID_SOURCES,
    DOI_ORG,
    DOI_SEARCHABLE_SOURCES,
)
from domain.types import JsonValue
from pipeline.http.circuit_breaker import SourceCircuitBreaker
from pipeline.http.fetch_pool import run_fetch_pool
from pipeline.http.polite_pool import build_user_agent
from pipeline.ingestion.common.failed_lookups import (
    forget_failed_doi_lookups,
    pending_failed_lookup_sql,
    record_failed_lookup,
)
from pipeline.ingestion.complements.doi_org import doi_existence
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.libelles import branche_de_source, rien_a_faire
from pipeline.runtime.observability.logging_scope import scoped_logger
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import progression
from pipeline.runtime.observability.signals import select_targets, skipped
from pipeline.runtime.parallel import RunParallel
from pipeline.task_runner import TaskRun, TaskStep, run_tasks

FetchChannel = Callable[[PhaseContext], PhaseMetrics]
"""Recherche HAL par hal-id ou par NNT : rend les métriques du canal."""
FetchDoiOne = Callable[[PhaseContext, str, SourceCircuitBreaker], PhaseMetrics]
"""Recherche par DOI dans une source cible, sous le circuit-breaker de la source."""

_HAL_BY_ID = "fetch_missing.hal_by_id"
_HAL_BY_NNT = "fetch_missing.hal_by_nnt"
_THESES_BY_NNT = "fetch_missing.theses_by_nnt"


def _doi_task(target: str) -> str:
    return f"fetch_missing.doi.{target}"


def _summary(metrics: PhaseMetrics) -> dict[str, float | None]:
    """Ligne « par canal » de la table d'observabilité de la phase."""
    return {
        "interrogated": metrics.total,
        "new": metrics.new,
        "not_found": metrics.extras.get("not_found", 0),
        "duration_s": metrics.duration_s,
    }


@dataclass(frozen=True)
class FetchMissingPhase:
    fetch_hal_by_id: FetchChannel
    fetch_hal_by_nnt: FetchChannel
    fetch_theses_by_nnt: FetchChannel
    fetch_doi_one: FetchDoiOne
    run_parallel: RunParallel

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute les canaux HAL puis le lot parallèle de la recherche par DOI, et assemble les métriques."""
        options = ctx.options
        hal = "hal" in options.sources
        theses = "theses" in options.sources
        # WoS opt-in.
        doi_targets = set(
            select_targets(DOI_SEARCHABLE_SOURCES, options.sources, include_wos=options.include_wos)
        )
        retenus = {
            _HAL_BY_ID: hal,
            _HAL_BY_NNT: hal and options.mode == "full",
            _THESES_BY_NNT: theses,
            **{_doi_task(target): target in doi_targets for target in DOI_SEARCHABLE_SOURCES},
        }

        def quand(task: str) -> Callable[[PhaseContext], bool]:
            return lambda _ctx: retenus[task]

        def channel(fetch: FetchChannel) -> TaskRun:
            return lambda ctx, _breaker: fetch(ctx)

        def doi(target: str) -> TaskRun:
            def run(ctx: PhaseContext, breaker: SourceCircuitBreaker | None) -> PhaseMetrics:
                assert breaker is not None, "tâche à source : l'exécuteur pose le circuit-breaker"
                return self.fetch_doi_one(ctx, target, breaker)

            return run

        by_task = run_tasks(
            "fetch_missing",
            {
                _HAL_BY_ID: TaskStep(
                    channel(self.fetch_hal_by_id),
                    section="Recherche dans HAL des documents avec hal-id trouvés ailleurs",
                    when=quand(_HAL_BY_ID),
                ),
                _HAL_BY_NNT: TaskStep(
                    channel(self.fetch_hal_by_nnt),
                    section="Recherche dans HAL des thèses avec NNT trouvées ailleurs",
                    when=quand(_HAL_BY_NNT),
                ),
                _THESES_BY_NNT: TaskStep(
                    channel(self.fetch_theses_by_nnt),
                    section="Recherche dans theses.fr des thèses avec NNT trouvées ailleurs",
                    when=quand(_THESES_BY_NNT),
                ),
                **{
                    _doi_task(target): TaskStep(
                        doi(target),
                        section="Recherche par DOI des documents manquants dans chaque source",
                        when=quand(_doi_task(target)),
                    )
                    for target in DOI_SEARCHABLE_SOURCES
                },
            },
            ctx,
            parallel=self.run_parallel,
        )

        doi_metrics = [by_task[_doi_task(target)] for target in doi_targets]
        # Une source sans DOI à chercher n'affiche rien : sans aucune barre ni signal, le titre resterait seul.
        if doi_metrics and all(m.total == 0 and not m.signals for m in doi_metrics):
            rien_a_faire(ctx.logger)

        metrics = PhaseMetrics()
        by_channel: dict[str, dict[str, float | None]] = {}
        channels = {
            _HAL_BY_ID: "hal-id",
            _HAL_BY_NNT: "NNT",
            _THESES_BY_NNT: "NNT theses.fr",
            **{_doi_task(target): target for target in DOI_SEARCHABLE_SOURCES},
        }
        for task, key in channels.items():
            metrics.merge(by_task[task])
            if retenus[task] and not skipped(by_task[task]):
                by_channel[key] = _summary(by_task[task])
        if by_channel:
            metrics.details["table"] = {
                "rows": [{"key": channel, **summary} for channel, summary in by_channel.items()]
            }
        return metrics


# ── Recherche par DOI ─────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DoiBatchResult:
    """Réponse d'une source à un lot de DOI : notices trouvées, et DOI dont la source a confirmé l'absence.

    Un DOI du lot présent dans aucune des deux listes attend le run suivant : la source était indisponible, ou sa réponse ne permet pas de conclure.

    Pour une agence d'enregistrement, les DOI absents sont soumis à doi.org : `known_to_doi_org` et `unknown_to_doi_org` rangent ceux qu'il connaît et ceux qu'il ne connaît pas.
    """

    records: list[Mapping[str, JsonValue]] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    known_to_doi_org: list[str] = field(default_factory=list)
    unknown_to_doi_org: list[str] = field(default_factory=list)


class DoiSearch(Protocol):
    """Recherche par DOI dans une source : requête d'un lot de DOI, écriture d'une notice reçue.

    Les attributs règlent la boucle : taille de lot, nombre de requêtes simultanées, pause de chaque worker après sa requête.
    """

    source_key: str
    batch_size: int  # 1 pour un appel par DOI, >1 pour un appel groupé
    max_concurrent: int  # plafond de requêtes simultanées, sous le rate-limit de l'API
    request_delay_s: float  # pause par worker après chaque requête (0 = pas de pause)

    def fetch_async(self, client: httpx2.AsyncClient, dois: list[str]) -> Awaitable[DoiBatchResult]:
        """Interroge l'API pour un lot de 1 à `batch_size` DOI."""

    def insert(self, conn: Connection, record: Mapping[str, JsonValue]) -> bool:
        """Écrit la notice dans `staging` et efface les échecs que ses DOI démentent. Rend `True` sur une insertion. Ne commite pas."""


# Pour crossref et datacite, les DOI candidats sont filtrés sur l'agence d'enregistrement (RA) de leur préfixe.
_TARGET_RA: dict[str, str] = {
    "crossref": "Crossref",
    "datacite": "DataCite",
}


def get_missing_dois(conn: Connection, target: str, *, retry_after_days: int) -> list[str]:
    """DOI présents dans les autres sources et absents de la cible.

    Pool (vue `candidate_dois`) restreint aux publications **in-périmètre** : `source_publications.doi` (DOI primaire) ∪ `external_ids.related_dois` (DOI secondaires : preprint/dépôt/édition) ∪ `publication_relations.target_doi` (cibles des relations : preprint/supplément/data paper… à rapatrier) ∪ DOI DataCite déduits de `external_ids.arxiv_id` (préfixe `10.48550/arXiv.<id>` : tout dépôt arXiv expose ce DOI DataCite). Le périmètre (`publications.in_perimeter`) est celui matérialisé au run précédent : ne chercher que les DOI de publications in-périmètre évite de rapatrier des documents hors périmètre. Les DOI de records fraîchement ingérés sont rattrapés au run suivant (pipeline convergent).

    Exclut les DOI que la cible porte déjà, en `source_publications.doi` comme en `external_ids.related_dois` : une source rend un même document pour l'un ou l'autre de ses identifiants, si bien qu'un DOI secondaire ramènerait un document déjà présent.

    Le SQL compare les `doi` par égalité directe. Les candidats retenus sont normalisés via `clean_doi` et dédoublonnés avant d'être renvoyés : les appels HTTP par DOI en aval reçoivent une forme canonique, quelle que soit la propreté de la valeur source.

    Exclut les DOI dont la recherche dans la cible a échoué il y a moins de `retry_after_days` jours (`failed_lookups`), et les DOI que doi.org ne connaît pas. Le pool se borne donc de lui-même : un DOI introuvable en sort jusqu'à l'échéance du délai, un DOI inexistant en sort définitivement.

    Pour les cibles présentes dans `_TARGET_RA`, retient seulement les DOI dont le préfixe est résolu vers l'agence de la cible. Un préfixe pas encore résolu attend la phase `resolve_ra`, plus loin dans le run : son DOI est cherché au run suivant, et jamais auprès des deux API.
    """
    if target not in VALID_SOURCES:
        raise ValueError(f"Source inconnue : {target}. Valides : {', '.join(VALID_SOURCES)}")

    target_ra = _TARGET_RA.get(target)
    join_clause = (
        "JOIN doi_prefixes dp ON dp.prefix = split_part(c.doi, '/', 1)" if target_ra else ""
    )
    # Exclusion du target : `source IS DISTINCT FROM` (relations à source NULL candidates pour toutes les cibles) + absent du staging du target + absent des DOI que la cible porte déjà. `NOT EXISTS` plutôt que `NOT IN` : un NULL dans la sous-requête viderait la sélection.
    prefix_filter = " AND dp.ra = :target_ra" if target_ra else ""
    pending = pending_failed_lookup_sql(source_sql=":target", id_type="doi", value_sql="c.doi")
    unknown_to_doi_org = pending_failed_lookup_sql(
        source_sql=f"'{DOI_ORG}'", id_type="doi", value_sql="c.doi"
    )
    query = f"""
        WITH deja_connus AS (
            SELECT sp.doi
            FROM source_publications sp
            WHERE sp.source = CAST(:target AS source_type) AND sp.doi IS NOT NULL
            UNION
            SELECT d.value
            FROM source_publications sp
            CROSS JOIN LATERAL jsonb_array_elements_text(sp.external_ids -> '{ExternalIdType.RELATED_DOIS}') d(value)
            WHERE sp.source = CAST(:target AS source_type)
              AND jsonb_typeof(sp.external_ids -> '{ExternalIdType.RELATED_DOIS}') = 'array'
        )
        SELECT DISTINCT c.doi
        FROM candidate_dois c
        {join_clause}
        WHERE c.source IS DISTINCT FROM :target
          AND NOT EXISTS (
                  SELECT 1 FROM staging s WHERE s.source = :target AND s.doi = c.doi
              ){prefix_filter}
          AND NOT EXISTS (SELECT 1 FROM deja_connus k WHERE k.doi = c.doi)
          AND NOT {pending}
          AND NOT {unknown_to_doi_org}
        ORDER BY c.doi
    """
    params: dict[str, str | int] = {"target": target, "retry_after_days": retry_after_days}
    if target_ra:
        params["target_ra"] = target_ra
    rows: ScalarResult[str] = conn.execute(text(query), params).scalars()
    # Re-nettoyage des candidats (idempotent) : `staging.doi` peut porter des DOI non normalisés ; `dict.fromkeys` dédoublonne en préservant l'ordre.
    return list(dict.fromkeys(c for d in rows if (c := clean_doi(d))))


async def fetch_missing_doi(
    conn: Connection,
    search: DoiSearch,
    log: logging.Logger,
    *,
    retry_after_days: int,
    limit: int | None = None,
    breaker: SourceCircuitBreaker | None = None,
) -> PhaseMetrics:
    """Cherche dans la source de `search` les DOI qu'elle n'a pas rendus, et écrit les notices trouvées dans `staging`.

    Les requêtes tournent en parallèle via `run_fetch_pool` (pool de `search.max_concurrent` workers), ce qui borne le débit au rate-limit de l'API. Les écritures restent séquentielles. Chaque lot est committé en une transaction.

    Un DOI confirmé absent est inscrit dans `failed_lookups`. Un DOI ni trouvé ni absent attend le run suivant. `limit` plafonne le nombre de DOI d'une exécution.

    Quand la source est l'agence d'enregistrement des DOI cherchés (`_TARGET_RA`), un DOI absent est soumis à doi.org. Un DOI que doi.org ne connaît pas est inscrit dans `failed_lookups` sous `DOI_ORG` ; un DOI qu'il connaît en est effacé.

    `total` = DOI traités, `new` = notices insérées, `extras["fetched"]` = notices reçues, `extras["not_found"]` = DOI confirmés absents, `extras["unknown_to_doi_org"]` = DOI que doi.org ne connaît pas.
    """
    slog = scoped_logger(log, search.source_key)
    dois = get_missing_dois(conn, search.source_key, retry_after_days=retry_after_days)

    if limit and len(dois) > limit:
        slog.info(
            "plafond de %d DOI par exécution, %d reportés aux suivantes", limit, len(dois) - limit
        )
        dois = dois[:limit]

    total = len(dois)
    if total == 0:
        return PhaseMetrics()

    batches = [dois[i : i + search.batch_size] for i in range(0, total, search.batch_size)]
    progress = {
        "processed": 0,
        "fetched": 0,
        "inserted": 0,
        "not_found": 0,
        "unknown_to_doi_org": 0,
    }
    user_agent = _doi_org_user_agent() if search.source_key in _TARGET_RA else None

    async def _fetch(client: httpx2.AsyncClient, item: tuple[int, list[str]]) -> DoiBatchResult:
        batch_idx, batch = item
        try:
            result = await search.fetch_async(client, batch)
            if user_agent is not None and result.not_found:
                known, unknown = await doi_existence(
                    client, result.not_found, user_agent=user_agent
                )
                result = replace(result, known_to_doi_org=known, unknown_to_doi_org=unknown)
        except Exception as e:
            slog.error("erreur sur lot %d (%d DOI) : %s", batch_idx, len(batch), e)
            result = DoiBatchResult()
        if search.request_delay_s:
            await asyncio.sleep(search.request_delay_s)
        return result

    with progression(
        total, branche_de_source(search.source_key), slog, compte_retenus=True
    ) as avancement:

        def _write(conn: Connection, item: tuple[int, list[str]], result: DoiBatchResult) -> None:
            batch_idx, batch = item
            progress["fetched"] += len(result.records)
            progress["not_found"] += len(result.not_found)

            # Un lot = une transaction (le pool commite après ce write). Sur erreur, rollback : le lot repart au prochain run.
            batch_inserted = 0
            try:
                for record in result.records:
                    if search.insert(conn, record):
                        batch_inserted += 1
                for doi in result.not_found:
                    record_failed_lookup(conn, search.source_key, "doi", doi)
                for doi in result.unknown_to_doi_org:
                    record_failed_lookup(conn, DOI_ORG, "doi", doi)
                forget_failed_doi_lookups(conn, DOI_ORG, result.known_to_doi_org)
                progress["inserted"] += batch_inserted
                progress["unknown_to_doi_org"] += len(result.unknown_to_doi_org)
            except Exception as e:
                conn.rollback()
                slog.warning(
                    "lot %d (%d DOI) : insertion échouée, rollback — %s", batch_idx, len(batch), e
                )

            progress["processed"] += len(batch)
            avancement.avance(len(batch))
            avancement.retient(batch_inserted)

        await run_fetch_pool(
            list(enumerate(batches)),
            conn,
            max_concurrent=search.max_concurrent,
            commit_every=1,
            fetch=_fetch,
            write=_write,
        )

    if breaker is not None and breaker.tripped:
        slog.warning(
            "indisponible (429/5xx répétés) — abandon, %d/%d DOI traités, reste au prochain run",
            progress["processed"],
            total,
        )

    return PhaseMetrics(
        seen=total,
        new=progress["inserted"],
        extras={
            "fetched": progress["fetched"],
            "not_found": progress["not_found"],
            "unknown_to_doi_org": progress["unknown_to_doi_org"],
        },
    )


def _doi_org_user_agent() -> str:
    """User-Agent du polite pool pour doi.org."""
    from pipeline.http.polite_pool import get_polite_pool_email

    return build_user_agent(get_polite_pool_email())


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    """Rattrapage des documents repérés dans une source mais absents d'une autre.

    La recherche dans HAL télécharge les documents présents dans HAL et absents du staging, repérés par leur hal-id dans OpenAlex et ScanR, ou par le NNT d'une thèse soutenue. La recherche dans theses.fr télécharge les thèses dont le NNT figure dans une autre source. La recherche par DOI vise ensuite, pour chaque source cible, les DOI vus dans les autres sources et absents de la sienne. WoS est opt-in (`--include-wos`) : crédit API limité, source exclue par défaut.

    Les deux se bornent d'elles-mêmes : un identifiant cherché en vain est inscrit dans `failed_lookups`, et cherché de nouveau après le délai `fetch_missing_retry_after_days`, sauf s'il est absent de son registre.
    """
    from pipeline.runtime.parallel import run_parallel

    return FetchMissingPhase(
        fetch_hal_by_id=_run_fetch_missing_hal_by_id,
        fetch_hal_by_nnt=_run_fetch_missing_hal_by_nnt,
        fetch_theses_by_nnt=_run_fetch_missing_theses_by_nnt,
        fetch_doi_one=_run_fetch_missing_doi,
        run_parallel=run_parallel,
    )


def _run_fetch_missing_hal_by_id(ctx: PhaseContext) -> PhaseMetrics:
    """Recherche dans HAL par hal-id (OpenAlex/ScanR) : documents absents du staging."""
    from pipeline.ingestion.hal.fetch_missing import fetch_missing_hal_by_id
    from pipeline.runtime.config import get_fetch_missing_retry_after_days

    with ctx.open_tx() as conn:
        retry_after_days = get_fetch_missing_retry_after_days(conn)
        return asyncio.run(
            fetch_missing_hal_by_id(conn, ctx.logger, retry_after_days=retry_after_days)
        )


def _run_fetch_missing_hal_by_nnt(ctx: PhaseContext) -> PhaseMetrics:
    """Recherche dans HAL par NNT (theses.fr) : thèses soutenues sans document HAL."""
    from pipeline.ingestion.hal.fetch_missing import fetch_missing_hal_by_nnt
    from pipeline.runtime.config import get_fetch_missing_retry_after_days

    with ctx.open_tx() as conn:
        retry_after_days = get_fetch_missing_retry_after_days(conn)
        return asyncio.run(
            fetch_missing_hal_by_nnt(conn, ctx.logger, retry_after_days=retry_after_days)
        )


def _run_fetch_missing_theses_by_nnt(ctx: PhaseContext) -> PhaseMetrics:
    """Recherche dans theses.fr par NNT : thèses trouvées dans d'autres sources, absentes du staging theses.fr."""
    from pipeline.ingestion.theses.fetch_missing import fetch_missing_theses_by_nnt
    from pipeline.runtime.config import get_fetch_missing_retry_after_days

    with ctx.open_tx() as conn:
        retry_after_days = get_fetch_missing_retry_after_days(conn)
        return asyncio.run(
            fetch_missing_theses_by_nnt(conn, ctx.logger, retry_after_days=retry_after_days)
        )


def _make_doi_search(target: str) -> DoiSearch:
    """Construit la recherche par DOI d'une source cible."""
    from pipeline.ingestion.crossref.fetch_missing import CrossrefDoiSearch
    from pipeline.ingestion.datacite.fetch_missing import DataciteDoiSearch
    from pipeline.ingestion.hal.fetch_missing import HalDoiSearch
    from pipeline.ingestion.openalex.fetch_missing import OpenalexDoiSearch
    from pipeline.ingestion.scanr.fetch_missing import ScanrDoiSearch
    from pipeline.ingestion.wos.fetch_missing import WosDoiSearch

    searches: dict[str, type[DoiSearch]] = {
        "hal": HalDoiSearch,
        "openalex": OpenalexDoiSearch,
        "wos": WosDoiSearch,
        "scanr": ScanrDoiSearch,
        "crossref": CrossrefDoiSearch,
        "datacite": DataciteDoiSearch,
    }
    return searches[target]()


def _run_fetch_missing_doi(
    ctx: PhaseContext, target: str, breaker: SourceCircuitBreaker
) -> PhaseMetrics:
    from pipeline.runtime.config import (
        get_fetch_missing_max_per_source,
        get_fetch_missing_retry_after_days,
    )

    search = _make_doi_search(target)
    with ctx.open_tx() as conn:
        retry_after_days = get_fetch_missing_retry_after_days(conn)
        limit = get_fetch_missing_max_per_source(conn)
        return asyncio.run(
            fetch_missing_doi(
                conn,
                search,
                ctx.logger,
                retry_after_days=retry_after_days,
                limit=limit,
                breaker=breaker,
            )
        )
