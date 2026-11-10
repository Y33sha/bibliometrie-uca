"""Nouvelle recherche des documents d'une source par leur identifiant natif (`staging.source_id`).

L'adaptateur de chaque source fournit sa requête par identifiant natif (`FetchOne`). `refresh` sélectionne les documents et les cherche par la boucle commune (`pipeline.ingestion.common.lookup`).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping

import httpx2
from sqlalchemy import Connection, text

from domain.documents.doc_types import DocType
from domain.sources.registry import Source
from domain.types import JsonValue
from pipeline.http.lookup import LookupOutcome
from pipeline.ingestion.common.lookup import LookupChannel, by_native_id, look_up
from pipeline.ingestion.common.staging import StagingStore
from pipeline.runtime.observability.metrics import PhaseMetrics

type FetchOutcome = LookupOutcome[Mapping[str, JsonValue]]
"""Document trouvé dans la source, ou son absence, ou l'indisponibilité de la source."""


type FetchOne = Callable[[httpx2.AsyncClient, str], Awaitable[FetchOutcome]]
"""Cherche un document de la source par son identifiant natif."""


_STALE_ROWS_SQL_TEMPLATE = """
    SELECT s.source_id
    FROM staging s
    LEFT JOIN source_records sr
      ON sr.source = s.source AND sr.source_id = s.source_id
    WHERE s.source = CAST(:source AS source_type)
      AND s.disappeared_at IS NULL
      AND s.last_seen_at < now() - make_interval(days => :days)
      {year_clause}
    ORDER BY s.id
"""
"""Filtre sur l'année (`{year_clause}`) : `publication_year` vient de `source_records`. Un document sans enregistrement source reste sélectionné."""


def get_stale_source_ids(
    conn: Connection, source: str, years: list[int] | None = None, *, after_days: int
) -> list[str]:
    """Renvoie les identifiants natifs des documents de la source non revus par le moissonnage depuis `after_days` jours, hors documents disparus.

    `years` borne la sélection aux documents de ces années, et aux thèses en cours.
    """
    if source not in Source:
        raise ValueError(f"Source inconnue : {source}. Valides : {', '.join(Source)}")
    params: dict[str, object] = {"source": source, "days": after_days}
    year_clause = ""
    if years is not None:
        # Une thèse en cours est sans année de soutenance : elle est cherchée quelle que soit la fenêtre.
        year_clause = (
            "AND (sr.publication_year IS NULL OR sr.publication_year = ANY(:years)"
            f" OR sr.doc_type = '{DocType.ONGOING_THESIS}')"
        )
        params["years"] = list(years)
    sql = text(_STALE_ROWS_SQL_TEMPLATE.format(year_clause=year_clause))
    return list(conn.execute(sql, params).scalars())


async def refresh(
    conn: Connection,
    source: str,
    fetch_one: FetchOne,
    log: logging.Logger,
    *,
    after_days: int,
    years: list[int] | None = None,
) -> PhaseMetrics:
    """Cherche de nouveau par identifiant natif les documents de la source non revus par le moissonnage depuis `after_days` jours.

    Un document absent de la source, ou renvoyé sous un autre identifiant natif, est marqué disparu. `years` borne la sélection (`get_stale_source_ids`).

    Renvoie les compteurs de `look_up` : documents réécrits (`updated`), identiques (`unchanged`), lots non servis (`errors`), absences confirmées (`disappeared`).
    """
    return await look_up(
        conn,
        log,
        LookupChannel(
            source=source,
            fetch=by_native_id(source, fetch_one),
            on_absent=lambda conn, source_id: StagingStore(conn).mark_disappeared(
                source, source_id
            ),
            # La lecture par identifiant natif renvoie le document entier : aucun plafond d'auteurs.
            stage=lambda staging, record: staging.stage(source, record, listed=False),
            absent_metric="disappeared",
        ),
        get_stale_source_ids(conn, source, years, after_days=after_days),
    )
