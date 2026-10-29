"""Nouvelle lecture des documents d'une source par leur identifiant natif (`staging.source_id`).

Chaque source implémente `StaleRefetch` (`pipeline/ingestion/<source>/fetch_stale.py`) : seule la requête par identifiant natif lui est propre. `refresh` sélectionne les documents et les relit par la boucle commune (`pipeline.ingestion.common.lookup`).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping

import httpx2
from sqlalchemy import Connection, text

from domain.publications.doc_types import DocType
from domain.sources.registry import ALL_SOURCES_SET as VALID_SOURCES
from domain.types import JsonValue
from pipeline.http.lookup import LookupOutcome
from pipeline.ingestion.common.lookup import LookupChannel, look_up, one_at_a_time
from pipeline.runtime.observability.metrics import PhaseMetrics

type FetchOutcome = LookupOutcome[Mapping[str, JsonValue]]
"""Document relu dans la source, ou son absence, ou l'indisponibilité de la source."""


class StaleRefetch(ABC):
    """Nouvelle lecture d'un document d'une source par son identifiant natif.

    Les sous-classes fixent `source_key` et `max_concurrent`, et implémentent `fetch_by_native_id`. Le débit suit le budget de la source (`api_params.MAX_PER_SECOND`).
    """

    source_key: str
    max_concurrent: int  # plafond de requêtes simultanées, sous le rate-limit de l'API

    @abstractmethod
    async def fetch_by_native_id(
        self, client: httpx2.AsyncClient, source_id: str
    ) -> FetchOutcome: ...


# Filtre sur l'année (`{year_clause}`) : `publication_year` vient de `source_records`. Un document sans enregistrement source reste sélectionné.
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

_SET_DISAPPEARED_SQL = text(
    """
    UPDATE staging SET disappeared_at = now()
    WHERE source = CAST(:source AS source_type) AND source_id = :source_id
      AND disappeared_at IS NULL
    """
)


def get_stale_source_ids(
    conn: Connection, source: str, years: list[int] | None = None, *, after_days: int
) -> list[str]:
    """Identifiants natifs des documents de la source que le moissonnage n'a pas revus depuis `after_days` jours, hors documents disparus.

    `years` borne la sélection aux documents de ces années, et aux thèses en cours.
    """
    if source not in VALID_SOURCES:
        raise ValueError(f"Source inconnue : {source}. Valides : {', '.join(VALID_SOURCES)}")
    params: dict[str, object] = {"source": source, "days": after_days}
    year_clause = ""
    if years is not None:
        # Une thèse en cours est sans année de soutenance : elle est relue quelle que soit la fenêtre.
        year_clause = (
            "AND (sr.publication_year IS NULL OR sr.publication_year = ANY(:years)"
            f" OR sr.doc_type = '{DocType.ONGOING_THESIS}')"
        )
        params["years"] = list(years)
    sql = text(_STALE_ROWS_SQL_TEMPLATE.format(year_clause=year_clause))
    return list(conn.execute(sql, params).scalars())


def set_disappeared(conn: Connection, source: str, source_id: str) -> None:
    """Marque disparu un document que la source dit absent. L'appelant commite."""
    conn.execute(_SET_DISAPPEARED_SQL, {"source": source, "source_id": source_id})


async def refresh(
    conn: Connection,
    refetch: StaleRefetch,
    log: logging.Logger,
    *,
    after_days: int,
    years: list[int] | None = None,
) -> PhaseMetrics:
    """Relit par identifiant natif les documents de la source que le moissonnage n'a pas revus depuis `after_days` jours. Un document que la source dit absent est marqué disparu. `years` borne la sélection (`get_stale_source_ids`).

    Rend les compteurs de `look_up` : documents réécrits (`updated`), identiques (`unchanged`), lots non servis (`errors`), absences confirmées (`disappeared`).
    """
    source = refetch.source_key
    return await look_up(
        conn,
        log,
        LookupChannel(
            source=source,
            fetch=one_at_a_time(refetch.fetch_by_native_id),
            on_absent=lambda conn, source_id: set_disappeared(conn, source, source_id),
            # La lecture par identifiant natif rend le document entier : aucun plafond d'auteurs.
            stage=lambda staging, record: staging.stage(source, record, listed=False),
            absent_metric="disappeared",
            max_concurrent=refetch.max_concurrent,
        ),
        get_stale_source_ids(conn, source, years, after_days=after_days),
    )
