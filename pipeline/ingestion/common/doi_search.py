"""Recherche par DOI dans une source cible : les DOI vus dans les autres sources et absents de la cible, interrogés par lots.

L'adaptateur de chaque source interrogeable par DOI fournit sa recherche (`DoiSearch`) : la requête d'un lot. `fetch_missing_doi` sélectionne les DOI et les cherche par la boucle commune (`pipeline.ingestion.common.lookup`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import Connection, ScalarResult, text

from domain.documents.identifiers import DOI
from domain.source_records.identifiers import SourceIdentifierType
from domain.sources.registry import PROFILES, Source
from domain.sources.staging import StagingEntryMode
from infrastructure.db.doi_targets import unversioned_doi_sql
from pipeline.ingestion.common.failed_lookups import (
    pending_failed_lookup_sql,
    record_failed_lookup,
)
from pipeline.ingestion.common.lookup import Fetch, LookupChannel, look_up
from pipeline.runtime.observability.logging_scope import scoped_logger
from pipeline.runtime.observability.metrics import PhaseMetrics


@dataclass(frozen=True, slots=True)
class DoiSearch:
    """Recherche par DOI dans une source."""

    fetch: Fetch
    """Requête d'un lot de 1 à `batch_size` DOI."""
    batch_size: int = 1


def get_missing_dois(
    conn: Connection, target: str, *, retry_after_days: int, years: list[int] | None = None
) -> list[str]:
    """Renvoie les DOI à chercher dans la cible : DOI des publications du périmètre absents de la cible, nettoyés et sans doublon.

    Les candidats viennent de la vue `candidate_dois` : DOI des enregistrements sources, cibles des relations entre publications, DOI DataCite déduits des identifiants arXiv. La forme sans version de chaque DOI à suffixe de version s'ajoute aux candidats. Quand elle existe, elle devient la cible des versions (sous-étape `doi_targets`). Le périmètre est celui du run précédent ; les DOI des enregistrements sources créés pendant le run attendent le run suivant.

    Un DOI est absent de la cible s'il manque à son `staging` et à tous les DOI de ses enregistrements sources : une source renvoie un même document pour chacun de ses DOI.

    Un DOI sort de la sélection pendant `retry_after_days` jours après une recherche vaine dans la cible (`failed_lookups`), et définitivement s'il est inconnu de doi.org (`dois.registered`).

    Pour une cible agence d'enregistrement, seuls comptent les DOI à préfixe résolu vers cette agence. Un préfixe encore sans agence attend la phase `dois`, plus loin dans le run : son DOI est cherché au run suivant, auprès d'une seule des deux agences.

    `years` borne les candidats à la fenêtre d'années du run : un DOI est retenu quand l'un des enregistrements sources de sa publication a son année dans la fenêtre. Les sources d'une même publication diffèrent souvent d'un an.
    """
    if target not in Source:
        raise ValueError(f"Source inconnue : {target}. Valides : {', '.join(Source)}")

    target_ra = PROFILES[Source(target)].registration_agency
    join_clause = (
        "JOIN doi_prefixes dp ON dp.prefix = split_part(c.doi, '/', 1)" if target_ra else ""
    )
    prefix_filter = " AND dp.ra = :target_ra" if target_ra else ""
    pending = pending_failed_lookup_sql(source_sql=":target", id_type="doi", value_sql="c.doi")
    unknown_to_doi_org = "EXISTS (SELECT 1 FROM dois x WHERE x.doi = c.doi AND NOT x.registered)"
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
    # `IS DISTINCT FROM` : un DOI de relation ou une forme sans version, sans source, est candidat pour toutes les cibles.
    # `NOT EXISTS` : avec `NOT IN`, un NULL dans la sous-requête viderait la sélection.
    query = f"""
        WITH deja_connus AS (
            SELECT d.id_value AS doi
            FROM source_records sr
            JOIN source_record_identifiers d ON d.source_record_id = sr.id
            WHERE sr.source = CAST(:target AS source_type)
              AND d.id_type = '{SourceIdentifierType.DOI.value}' AND d.removed_by IS NULL
        )
        SELECT DISTINCT c.doi
        FROM (
            SELECT doi, source, publication_id FROM candidate_dois
            UNION
            SELECT {unversioned_doi_sql("doi")}, NULL, publication_id FROM candidate_dois
            WHERE {unversioned_doi_sql("doi")} IS NOT NULL
        ) c
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
    # `staging.doi` peut contenir des DOI non normalisés : les candidats repassent par `DOI.normalize`, puis `dict.fromkeys` dédoublonne en gardant l'ordre.
    return list(dict.fromkeys(c for d in rows if (c := DOI.normalize(d))))


async def fetch_missing_doi(
    conn: Connection,
    source: str,
    search: DoiSearch,
    log: logging.Logger,
    *,
    retry_after_days: int,
    limit: int | None = None,
    years: list[int] | None = None,
    scope: str | None = None,
) -> PhaseMetrics:
    """Cherche dans la source les DOI absents de son `staging`, et écrit dans `staging` les documents trouvés.

    Un DOI absent de la source est inscrit dans `failed_lookups`. `limit` plafonne le nombre de DOI d'une exécution. `scope` nomme l'identifiant au journal (`LookupChannel.scope`). Renvoie les compteurs de `look_up`.
    """
    dois = get_missing_dois(conn, source, retry_after_days=retry_after_days, years=years)
    if limit and len(dois) > limit:
        scoped_logger(log, source, scope).info(
            "plafond de %d DOI par exécution, %d reportés aux suivantes", limit, len(dois) - limit
        )
        dois = dois[:limit]

    return await look_up(
        conn,
        log,
        LookupChannel(
            source=source,
            fetch=search.fetch,
            on_absent=lambda conn, doi: record_failed_lookup(conn, source, "doi", doi),
            stage=lambda staging, record: staging.stage(
                source, record, entry_mode=StagingEntryMode.FETCH_MISSING_DOI
            ),
            batch_size=search.batch_size,
            scope=scope,
        ),
        dois,
    )
