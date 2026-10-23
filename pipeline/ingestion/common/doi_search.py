"""Recherche par DOI dans une source cible : les DOI vus dans les autres sources et absents de la cible, interrogés par lots.

Chaque source implémente `DoiSearch` (`pipeline/ingestion/<source>/fetch_missing.py`) : requête d'un lot, écriture d'un enregistrement source. `fetch_missing_doi` fait la boucle commune.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field, replace
from typing import Protocol

import httpx2
from sqlalchemy import Connection, ScalarResult, text

from domain.publications.identifiers import clean_doi
from domain.source_records.external_ids import ExternalIdType
from domain.sources.registry import (
    ALL_SOURCES_SET as VALID_SOURCES,
    DOI_ORG,
    PROFILES,
    Source,
)
from domain.types import JsonValue
from pipeline.http.circuit_breaker import source_tripped
from pipeline.http.fetch_pool import run_fetch_pool
from pipeline.http.polite_pool import polite_user_agent
from pipeline.ingestion.common.failed_lookups import (
    forget_failed_doi_lookups,
    pending_failed_lookup_sql,
    record_failed_lookup,
)
from pipeline.ingestion.complements.doi_org import doi_existence
from pipeline.runtime.observability.log_format import source_branch
from pipeline.runtime.observability.logging_scope import scoped_logger
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress


@dataclass(frozen=True, slots=True)
class DoiBatchResult:
    """Réponse d'une source à un lot de DOI : enregistrements sources trouvés, et DOI dont la source a confirmé l'absence.

    Un DOI du lot présent dans aucune des deux listes attend le run suivant : la source était indisponible, ou sa réponse ne permet pas de conclure.

    Pour une agence d'enregistrement, les DOI absents sont soumis à doi.org : `known_to_doi_org` et `unknown_to_doi_org` rangent ceux qu'il connaît et ceux qu'il ne connaît pas.
    """

    records: list[Mapping[str, JsonValue]] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    known_to_doi_org: list[str] = field(default_factory=list)
    unknown_to_doi_org: list[str] = field(default_factory=list)


class DoiSearch(Protocol):
    """Recherche par DOI dans une source : requête d'un lot de DOI, écriture d'un enregistrement source reçu.

    Les attributs règlent la boucle : taille de lot, nombre de requêtes simultanées, pause de chaque worker après sa requête.
    """

    source_key: str
    batch_size: int  # 1 pour un appel par DOI, >1 pour un appel groupé
    max_concurrent: int  # plafond de requêtes simultanées, sous le rate-limit de l'API
    request_delay_s: float  # pause par worker après chaque requête (0 = pas de pause)

    def fetch_async(self, client: httpx2.AsyncClient, dois: list[str]) -> Awaitable[DoiBatchResult]:
        """Interroge l'API pour un lot de 1 à `batch_size` DOI."""

    def insert(self, conn: Connection, record: Mapping[str, JsonValue]) -> bool:
        """Écrit l'enregistrement source dans `staging` et efface les échecs que ses DOI démentent. Rend `True` sur une insertion. Ne commite pas."""


def get_missing_dois(conn: Connection, target: str, *, retry_after_days: int) -> list[str]:
    """DOI présents dans les autres sources et absents de la cible.

    Pool (vue `candidate_dois`) restreint aux publications **in-périmètre** : `source_records.doi` (DOI primaire) ∪ `external_ids.related_dois` (DOI secondaires : preprint/dépôt/édition) ∪ `publication_relations.target_doi` (cibles des relations : preprint/supplément/data paper… à rapatrier) ∪ DOI DataCite déduits de `external_ids.arxiv_id` (préfixe `10.48550/arXiv.<id>` : tout dépôt arXiv expose ce DOI DataCite). Le périmètre (`publications.in_perimeter`) est celui matérialisé au run précédent : ne chercher que les DOI de publications in-périmètre évite de rapatrier des documents hors périmètre. Les DOI de records fraîchement ingérés sont rattrapés au run suivant (pipeline convergent).

    Exclut les DOI que la cible porte déjà, en `source_records.doi` comme en `external_ids.related_dois` : une source rend un même document pour l'un ou l'autre de ses identifiants, si bien qu'un DOI secondaire ramènerait un document déjà présent.

    Le SQL compare les `doi` par égalité directe. Les candidats retenus sont normalisés via `clean_doi` et dédoublonnés avant d'être renvoyés : les appels HTTP par DOI en aval reçoivent une forme canonique, quelle que soit la propreté de la valeur source.

    Exclut les DOI dont la recherche dans la cible a échoué il y a moins de `retry_after_days` jours (`failed_lookups`), et les DOI que doi.org ne connaît pas. Le pool se borne donc de lui-même : un DOI introuvable en sort jusqu'à l'échéance du délai, un DOI inexistant en sort définitivement.

    Pour une cible agence d'enregistrement (`SourceProfile.registration_agency`), retient seulement les DOI dont le préfixe est résolu vers l'agence de la cible. Un préfixe pas encore résolu attend la phase `resolve_ra`, plus loin dans le run : son DOI est cherché au run suivant, et jamais auprès des deux API.
    """
    if target not in VALID_SOURCES:
        raise ValueError(f"Source inconnue : {target}. Valides : {', '.join(VALID_SOURCES)}")

    target_ra = PROFILES[Source(target)].registration_agency
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
            SELECT sr.doi
            FROM source_records sr
            WHERE sr.source = CAST(:target AS source_type) AND sr.doi IS NOT NULL
            UNION
            SELECT d.value
            FROM source_records sr
            CROSS JOIN LATERAL jsonb_array_elements_text(sr.external_ids -> '{ExternalIdType.RELATED_DOIS}') d(value)
            WHERE sr.source = CAST(:target AS source_type)
              AND jsonb_typeof(sr.external_ids -> '{ExternalIdType.RELATED_DOIS}') = 'array'
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
) -> PhaseMetrics:
    """Cherche dans la source de `search` les DOI qu'elle n'a pas rendus, et écrit les enregistrements sources trouvés dans `staging`.

    Les requêtes tournent en parallèle via `run_fetch_pool` (pool de `search.max_concurrent` workers), ce qui borne le débit au rate-limit de l'API. Les écritures restent séquentielles. Chaque lot est committé en une transaction.

    Un DOI confirmé absent est inscrit dans `failed_lookups`. Un DOI ni trouvé ni absent attend le run suivant. `limit` plafonne le nombre de DOI d'une exécution.

    Quand la source est l'agence d'enregistrement des DOI cherchés, un DOI absent est soumis à doi.org. Un DOI que doi.org ne connaît pas est inscrit dans `failed_lookups` sous `DOI_ORG` ; un DOI qu'il connaît en est effacé.

    `total` = DOI traités, `new` = enregistrements sources insérés, `extras["fetched"]` = enregistrements sources reçus, `extras["not_found"]` = DOI confirmés absents, `extras["unknown_to_doi_org"]` = DOI que doi.org ne connaît pas.
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
    is_agency = PROFILES[Source(search.source_key)].registration_agency is not None
    user_agent = polite_user_agent() if is_agency else None

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

    with track_progress(total, source_branch(search.source_key), slog, count_kept=True) as bar:

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
            bar.advance(len(batch))
            bar.keep(batch_inserted)

        await run_fetch_pool(
            list(enumerate(batches)),
            conn,
            max_concurrent=search.max_concurrent,
            commit_every=1,
            fetch=_fetch,
            write=_write,
        )

    if source_tripped():
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
