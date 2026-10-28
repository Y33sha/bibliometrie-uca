"""Recherche par DOI dans une source cible : les DOI vus dans les autres sources et absents de la cible, interrogés par lots.

Chaque source implémente `DoiSearch` (`pipeline/ingestion/<source>/fetch_missing.py`) : la requête d'un lot. `fetch_missing_doi` sélectionne les DOI et les cherche par la boucle commune (`pipeline.ingestion.common.lookup`).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Protocol

import httpx2
from sqlalchemy import Connection, ScalarResult, text

from domain.publications.identifiers import clean_doi
from domain.sources.registry import (
    ALL_SOURCES_SET as VALID_SOURCES,
    DOI_ORG,
    PROFILES,
    Source,
)
from domain.sources.staging import StagingEntryMode
from infrastructure.db.source_record_identifiers import related_doi_sql
from pipeline.http.lookup import UNAVAILABLE, Unavailable
from pipeline.http.polite_pool import polite_user_agent
from pipeline.ingestion.common.failed_lookups import (
    pending_failed_lookup_sql,
    record_failed_lookup,
)
from pipeline.ingestion.common.lookup import LookupBatch, LookupChannel, look_up
from pipeline.ingestion.complements.doi_org import doi_existence
from pipeline.runtime.observability.logging_scope import scoped_logger
from pipeline.runtime.observability.metrics import PhaseMetrics


class DoiSearch(Protocol):
    """Recherche par DOI dans une source : requête d'un lot de DOI.

    Les attributs règlent la boucle : taille de lot, nombre de requêtes simultanées. Le débit suit le budget de la source (`api_params.MAX_PER_SECOND`).
    """

    source_key: str
    batch_size: int  # 1 pour un appel par DOI, >1 pour un appel groupé
    max_concurrent: int  # plafond de requêtes simultanées, sous le rate-limit de l'API

    def fetch_async(
        self, client: httpx2.AsyncClient, dois: list[str]
    ) -> Awaitable[LookupBatch | Unavailable]:
        """Interroge l'API pour un lot de 1 à `batch_size` DOI."""


def get_missing_dois(
    conn: Connection, target: str, *, retry_after_days: int, years: list[int] | None = None
) -> list[str]:
    """DOI présents dans les autres sources et absents de la cible.

    `years` borne les candidats à la fenêtre d'années du run : un DOI est retenu quand l'un des enregistrements sources de sa publication a son année dans la fenêtre. Les sources d'une même publication diffèrent souvent d'un an. `None` : aucune borne.

    Pool (vue `candidate_dois`) restreint aux publications **in-périmètre** : `source_records.doi` (DOI primaire) ∪ autres DOI actifs des enregistrements sources (preprint/dépôt/édition) ∪ `publication_relations.target_doi` (cibles des relations : preprint/supplément/data paper… à rapatrier) ∪ DOI DataCite déduits de l'identifiant arXiv (préfixe `10.48550/arXiv.<id>` : tout dépôt arXiv expose ce DOI DataCite). Le périmètre (`publications.in_perimeter`) est celui matérialisé au run précédent : ne chercher que les DOI de publications in-périmètre évite de rapatrier des documents hors périmètre. Les DOI de records fraîchement ingérés sont rattrapés au run suivant (pipeline convergent).

    Exclut les DOI que la cible porte déjà, en `source_records.doi` comme parmi ses autres DOI actifs : une source rend un même document pour l'un ou l'autre de ses identifiants, si bien qu'un DOI secondaire ramènerait un document déjà présent.

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
    year_filter = (
        """
          AND EXISTS (
                  SELECT 1 FROM source_records sr_year
                  WHERE sr_year.publication_id = c.publication_id
                    AND sr_year.publication_year = ANY(:years)
              )"""
        if years is not None
        else ""
    )
    query = f"""
        WITH deja_connus AS (
            SELECT sr.doi
            FROM source_records sr
            WHERE sr.source = CAST(:target AS source_type) AND sr.doi IS NOT NULL
            UNION
            SELECT d.id_value
            FROM source_records sr
            JOIN source_record_identifiers d
              ON d.source_record_id = sr.id AND {related_doi_sql("d", "sr")}
            WHERE sr.source = CAST(:target AS source_type)
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
          AND NOT {unknown_to_doi_org}{year_filter}
        ORDER BY c.doi
    """
    params: dict[str, object] = {"target": target, "retry_after_days": retry_after_days}
    if years is not None:
        params["years"] = years
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
    years: list[int] | None = None,
) -> PhaseMetrics:
    """Cherche dans la source de `search` les DOI qu'elle n'a pas rendus, et écrit les enregistrements sources trouvés dans `staging`.

    Un DOI confirmé absent est inscrit dans `failed_lookups`. `limit` plafonne le nombre de DOI d'une exécution, `years` borne les candidats à la fenêtre d'années du run (`get_missing_dois`). Quand la source est l'agence d'enregistrement des DOI cherchés, ses DOI absents sont soumis à doi.org : un DOI que doi.org ne connaît pas est inscrit dans `failed_lookups` sous `DOI_ORG`.

    Compteurs de `look_up`, et `extras["unknown_to_doi_org"]` = DOI que doi.org ne connaît pas.
    """
    source = search.source_key
    dois = get_missing_dois(conn, source, retry_after_days=retry_after_days, years=years)
    if limit and len(dois) > limit:
        scoped_logger(log, source).info(
            "plafond de %d DOI par exécution, %d reportés aux suivantes", limit, len(dois) - limit
        )
        dois = dois[:limit]

    absent: list[str] = []

    def _absent(conn: Connection, doi: str) -> None:
        record_failed_lookup(conn, source, "doi", doi)
        absent.append(doi)

    metrics = await look_up(
        conn,
        log,
        LookupChannel(
            source=source,
            fetch=search.fetch_async,
            on_absent=_absent,
            stage=lambda staging, record: staging.stage(
                source, record, entry_mode=StagingEntryMode.FETCH_MISSING_DOI
            ),
            batch_size=search.batch_size,
            max_concurrent=search.max_concurrent,
        ),
        dois,
    )
    if absent and PROFILES[Source(source)].registration_agency is not None:
        checked = await look_up(conn, log, _doi_org_channel(), absent)
        metrics.add(unknown_to_doi_org=checked.extras.get("unknown_to_doi_org", 0))
    return metrics


def _doi_org_channel() -> LookupChannel:
    """Vérification auprès de doi.org de DOI qu'une agence d'enregistrement ignore. Un DOI que doi.org ne connaît pas est inscrit dans `failed_lookups` sous `DOI_ORG`."""
    user_agent = polite_user_agent()

    async def _fetch(client: httpx2.AsyncClient, dois: list[str]) -> LookupBatch | Unavailable:
        known, unknown = await doi_existence(client, dois, user_agent=user_agent)
        return LookupBatch(absent=unknown) if known or unknown else UNAVAILABLE

    return LookupChannel(
        source=DOI_ORG,
        fetch=_fetch,
        on_absent=lambda conn, doi: record_failed_lookup(conn, DOI_ORG, "doi", doi),
        absent_metric="unknown_to_doi_org",
        max_concurrent=3,
        shown=False,
    )
