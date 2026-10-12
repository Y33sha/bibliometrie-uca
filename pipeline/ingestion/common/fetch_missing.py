"""Phase `fetch_missing` : rattrapage des documents repérés dans une source mais absents d'une autre. Deux mécanismes, dans cet ordre :

1. **Recherche dans HAL** (`pipeline.ingestion.hal.fetch_missing`) : par hal-id (repéré dans OpenAlex et ScanR), puis par NNT (thèses sans document HAL).
2. **Recherche par DOI** : pour chaque source cible configurée, en parallèle, les DOI vus ailleurs et absents de la cible. Nœuds `fetch_missing.doi.<source>`.

Un identifiant cherché en vain est inscrit dans `failed_lookups` (`pipeline.ingestion.common.failed_lookups`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from typing import Protocol

import httpx2
from sqlalchemy import Connection, ScalarResult, text

from domain.publications.identifiers import clean_doi
from domain.source_publications.external_ids import ExternalIdType
from domain.sources.registry import ALL_SOURCES_SET as VALID_SOURCES, DOI_SEARCHABLE_SOURCES
from domain.types import JsonValue
from pipeline.ingestion.common.failed_lookups import pending_failed_lookup_sql, record_failed_lookup
from pipeline.ingestion.common.parallel import RunParallel
from pipeline.ingestion.http.circuit_breaker import SourceCircuitBreaker
from pipeline.ingestion.http.fetch_pool import run_fetch_pool
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.execution import credentials_missing, log, open_tx, under_circuit_breaker
from pipeline.runtime.libelles import branche_de_source, etape, rien_a_faire
from pipeline.runtime.logging_scope import scoped_logger
from pipeline.runtime.metrics import PhaseMetrics
from pipeline.runtime.progression import progression
from pipeline.runtime.signals import filter_configured, select_targets, timed_metrics

FetchChannel = Callable[[], PhaseMetrics]
"""Recherche HAL par hal-id ou par NNT : rend les métriques du canal."""
FetchDoiOne = Callable[[str], PhaseMetrics]
"""Recherche par DOI dans une source cible, sous circuit-breaker."""
CredentialsMissing = Callable[[str], "str | None"]
"""`(source) -> motif d'absence de credentials | None si configurée`."""


def _summary(metrics: PhaseMetrics, duration_s: float) -> dict[str, float]:
    """Ligne « par canal » de la table d'observabilité de la phase."""
    return {
        "interrogated": metrics.total,
        "new": metrics.new,
        "not_found": metrics.extras.get("not_found", 0),
        "duration_s": round(duration_s, 1),
    }


@dataclass(frozen=True)
class FetchMissingPhase:
    fetch_hal_by_id: FetchChannel
    fetch_hal_by_nnt: FetchChannel
    fetch_doi_one: FetchDoiOne
    run_parallel: RunParallel
    credentials_missing: CredentialsMissing

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Enchaîne les canaux HAL puis la recherche par DOI parallèle, et assemble les métriques."""
        options, logger = ctx.options, ctx.logger
        sources = options.sources or None
        metrics = PhaseMetrics()
        by_channel: dict[str, dict[str, float]] = {}

        # Étape 1 : recherche dans HAL, deux canaux distincts (hal-id, NNT).
        if not sources or "hal" in sources:
            etape(logger, "Recherche dans HAL des documents avec hal-id trouvés ailleurs")
            id_metrics, id_duration = timed_metrics(self.fetch_hal_by_id)
            metrics.merge(id_metrics)
            by_channel["hal-id"] = _summary(id_metrics, id_duration)

            if options.mode == "full":
                etape(logger, "Recherche dans HAL des thèses avec NNT trouvées ailleurs")
                nnt_metrics, nnt_duration = timed_metrics(self.fetch_hal_by_nnt)
                metrics.merge(nnt_metrics)
                by_channel["NNT"] = _summary(nnt_metrics, nnt_duration)

        # Étape 2 : par DOI. WoS opt-in, filtre `--sources` optionnel, ordre du registre des sources.
        doi_targets = select_targets(
            DOI_SEARCHABLE_SOURCES, sources, include_wos=options.include_wos
        )
        configured = filter_configured(
            doi_targets,
            metrics,
            credentials_missing=self.credentials_missing,
            logger=logger,
            phase="fetch_missing",
        )

        if configured:
            etape(logger, "Recherche par DOI des documents manquants dans chaque source")
            outcomes = self.run_parallel(
                {
                    target: partial(timed_metrics, partial(self.fetch_doi_one, target))
                    for target in configured
                }
            )
            for target, (channel_metrics, duration) in outcomes.items():
                metrics.merge(channel_metrics)
                by_channel[target] = _summary(channel_metrics, duration)
            # Une source sans DOI à chercher n'affiche rien : sans aucune barre ni signal, le titre resterait seul.
            if all(m.total == 0 and not m.signals for m, _ in outcomes.values()):
                rien_a_faire(logger)

        if by_channel:
            metrics.details["table"] = {
                "rows": [{"key": channel, **summary} for channel, summary in by_channel.items()]
            }
        # Les compteurs des trois sous-étapes couvrent des ensembles différents : les rapprocher en une ligne induirait en erreur. Chaque barre affiche son résultat, et la table d'observabilité le détail.
        metrics.resume = ""
        return metrics


# ── Recherche par DOI ─────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DoiBatchResult:
    """Réponse d'une source à un lot de DOI : notices trouvées, et DOI dont la source a confirmé l'absence.

    Un DOI du lot présent dans aucune des deux listes attend le run suivant : la source était indisponible, ou sa réponse ne permet pas de conclure.
    """

    records: list[Mapping[str, JsonValue]] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)


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


def get_missing_dois(conn: Connection, target: str) -> list[str]:
    """DOI présents dans les autres sources et absents de la cible.

    Pool (vue `candidate_dois`) restreint aux publications **in-périmètre** : `source_publications.doi` (DOI primaire) ∪ `external_ids.related_dois` (DOI secondaires : preprint/dépôt/édition) ∪ `publication_relations.target_doi` (cibles des relations : preprint/supplément/data paper… à rapatrier) ∪ DOI DataCite déduits de `external_ids.arxiv_id` (préfixe `10.48550/arXiv.<id>` : tout dépôt arXiv expose ce DOI DataCite). Le périmètre (`publications.in_perimeter`) est celui matérialisé au run précédent : ne chercher que les DOI de publications in-périmètre évite de rapatrier des documents hors périmètre. Les DOI de records fraîchement ingérés sont rattrapés au run suivant (pipeline convergent).

    Exclut les DOI que la cible porte déjà, en `source_publications.doi` comme en `external_ids.related_dois` : une source rend un même document pour l'un ou l'autre de ses identifiants, si bien qu'un DOI secondaire ramènerait un document déjà présent.

    Le SQL compare les `doi` par égalité directe. Les candidats retenus sont normalisés via `clean_doi` et dédoublonnés avant d'être renvoyés : les appels HTTP par DOI en aval reçoivent une forme canonique, quelle que soit la propreté de la valeur source.

    Exclut les DOI dont la recherche dans la cible a échoué et attend encore sa reprise (`failed_lookups`). Le pool se borne donc de lui-même : un DOI introuvable en sort jusqu'à l'échéance de son délai, ou définitivement quand il est l'identifiant natif de la cible.

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
        ORDER BY c.doi
    """
    params: dict[str, str] = {"target": target}
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

    `total` = DOI traités, `new` = notices insérées, `extras["fetched"]` = notices reçues, `extras["not_found"]` = DOI confirmés absents.
    """
    slog = scoped_logger(log, search.source_key)
    dois = get_missing_dois(conn, search.source_key)

    if limit and len(dois) > limit:
        slog.info(
            "plafond de %d DOI par exécution, %d reportés aux suivantes", limit, len(dois) - limit
        )
        dois = dois[:limit]

    total = len(dois)
    if total == 0:
        return PhaseMetrics()

    batches = [dois[i : i + search.batch_size] for i in range(0, total, search.batch_size)]
    progress = {"processed": 0, "fetched": 0, "inserted": 0, "not_found": 0}

    async def _fetch(client: httpx2.AsyncClient, item: tuple[int, list[str]]) -> DoiBatchResult:
        batch_idx, batch = item
        try:
            result = await search.fetch_async(client, batch)
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
                    record_failed_lookup(
                        conn, search.source_key, "doi", doi, retry_after_days=retry_after_days
                    )
                progress["inserted"] += batch_inserted
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
            should_continue=lambda: breaker is None or not breaker.tripped,
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
        extras={"fetched": progress["fetched"], "not_found": progress["not_found"]},
    )


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    """Rattrapage des documents repérés dans une source mais absents d'une autre.

    La recherche dans HAL télécharge les documents que HAL détient et que le staging n'a pas, repérés par leur hal-id dans OpenAlex et ScanR, ou par le NNT d'une thèse soutenue. La recherche par DOI vise ensuite, pour chaque source cible, les DOI vus dans les autres sources et absents de la sienne. WoS est opt-in (`--include-wos`) : crédit API limité, source exclue par défaut.

    Les deux se bornent d'elles-mêmes : un identifiant cherché en vain est inscrit dans `failed_lookups`, avec un délai avant la prochaine tentative, ou définitivement quand il est natif de la source.
    """
    from pipeline.ingestion.common.parallel import run_parallel

    return FetchMissingPhase(
        fetch_hal_by_id=_run_fetch_missing_hal_by_id,
        fetch_hal_by_nnt=_run_fetch_missing_hal_by_nnt,
        fetch_doi_one=_run_fetch_missing_doi,
        run_parallel=run_parallel,
        credentials_missing=credentials_missing,
    )


def _run_fetch_missing_hal_by_id() -> PhaseMetrics:
    """Recherche dans HAL par hal-id (OpenAlex/ScanR) : documents absents du staging."""
    from pipeline.ingestion.hal.fetch_missing import fetch_missing_hal_by_id
    from pipeline.runtime.config import get_fetch_missing_retry_after_days

    with open_tx() as conn:
        retry_after_days = get_fetch_missing_retry_after_days(conn)
        return under_circuit_breaker(
            "hal",
            lambda _breaker: asyncio.run(
                fetch_missing_hal_by_id(conn, log, retry_after_days=retry_after_days)
            ),
            phase="fetch_missing",
            logger=log,
        )


def _run_fetch_missing_hal_by_nnt() -> PhaseMetrics:
    """Recherche dans HAL par NNT (theses.fr) : thèses soutenues sans document HAL."""
    from pipeline.ingestion.hal.fetch_missing import fetch_missing_hal_by_nnt
    from pipeline.runtime.config import get_fetch_missing_retry_after_days

    with open_tx() as conn:
        retry_after_days = get_fetch_missing_retry_after_days(conn)
        return under_circuit_breaker(
            "hal",
            lambda _breaker: asyncio.run(
                fetch_missing_hal_by_nnt(conn, log, retry_after_days=retry_after_days)
            ),
            phase="fetch_missing",
            logger=log,
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


def _run_fetch_missing_doi(target: str) -> PhaseMetrics:
    from pipeline.runtime.config import (
        get_fetch_missing_max_per_source,
        get_fetch_missing_retry_after_days,
    )

    search = _make_doi_search(target)
    with open_tx() as conn:
        retry_after_days = get_fetch_missing_retry_after_days(conn)
        limit = get_fetch_missing_max_per_source(conn)
        return under_circuit_breaker(
            target,
            lambda breaker: asyncio.run(
                fetch_missing_doi(
                    conn,
                    search,
                    log,
                    retry_after_days=retry_after_days,
                    limit=limit,
                    breaker=breaker,
                )
            ),
            phase="fetch_missing",
            logger=log,
        )
