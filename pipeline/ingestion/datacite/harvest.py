"""Moissonnage DataCite : tâche `harvest.datacite`.

Interroge `GET /dois`, année par année, sur les affiliations des créateurs (`creators.affiliation.name`) qui contiennent l'un des mots-clés du périmètre de moissonnage, avec une pagination par curseur. La phase `affiliations` tranche ensuite quelles contributions sources relèvent du périmètre.

Les paramètres de requête comprennent `RECORD_PARAMS` (`api.py`), comme ceux des phases `fetch_missing` et `fetch_stale`. Le lien `next` de la pagination les reprend.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection

from infrastructure.read_models.perimeters.queries import get_extraction_api_ids
from pipeline.http.circuit_breaker import SourceUnavailableError
from pipeline.ingestion.common.harvester import (
    HarvestConfigError,
    HarvestWindow,
    SourceHarvester,
    stage_document,
)
from pipeline.ingestion.datacite.api import DataciteClient
from pipeline.runtime.observability.logging_scope import scoped_logger
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress


@dataclass(frozen=True)
class DataciteHarvestConfig:
    """Configuration du moissonnage DataCite, lue en base."""

    # Mots-clés cherchés dans les affiliations des créateurs.
    keywords: list[str]


def build_query(year: int, keywords: list[str]) -> str:
    """Requête `query` DataCite : DOI publiés l'année `year` dont une affiliation de créateur contient l'un des mots-clés, chacun cherché comme expression exacte."""
    clauses = " OR ".join(
        'creators.affiliation.name:"{}"'.format(k.replace("\\", "\\\\").replace('"', '\\"'))
        for k in keywords
    )
    return f"publicationYear:{year} AND ({clauses})"


def harvest_year(
    client: DataciteClient,
    conn: Connection,
    year: int,
    keywords: list[str],
    progress: Progress,
    metrics: PhaseMetrics,
) -> None:
    """Moissonne les DOI d'une année, page après page, et les compte dans `metrics`. Une ressource sans DOI est ignorée."""
    next_url: str | None = None
    query = build_query(year, keywords)
    while True:
        page = client.fetch_page(query, next_url, str(year))
        for record in page.records:
            stage_document(conn, metrics, source="datacite", record=record)
        conn.commit()
        progress.advance(len(page.records))
        next_url = page.next_url
        if next_url is None:
            return


class DataciteHarvester(SourceHarvester[DataciteHarvestConfig, DataciteClient]):
    """Moissonnage DataCite : les DOI dont une affiliation de créateur contient un mot-clé du périmètre, année par année.

    Une erreur sur une année est journalisée, et l'extraction passe à la suivante.
    """

    SOURCE = "datacite"

    def load_config(self, conn: Connection) -> DataciteHarvestConfig:
        keywords = get_extraction_api_ids(conn, "datacite")
        if not keywords:
            raise HarvestConfigError(
                "aucun mot-clé (api_ids->'datacite' vide pour le périmètre d'extraction)"
            )
        return DataciteHarvestConfig(keywords=keywords)

    def harvest_all(self, window: HarvestWindow, config: DataciteHarvestConfig) -> PhaseMetrics:
        keywords = config.keywords
        client = self._client
        years = self._years(window)

        def count_year(year: int) -> int:
            try:
                return client.count(build_query(year, keywords), str(year))
            except SourceUnavailableError:
                raise
            except Exception:
                # L'extraction de l'année rencontre la même erreur et la signale.
                return 0

        def harvest_step(year: int, progress: Progress) -> PhaseMetrics:
            # Une erreur garde les métriques des pages déjà écrites.
            metrics = PhaseMetrics()
            try:
                harvest_year(client, self.conn, year, keywords, progress, metrics)
            except SourceUnavailableError:
                raise
            except Exception as e:
                scoped_logger(self.logger, self.SOURCE, str(year)).error(
                    "erreur : %s — passage à la suivante", e
                )
            return metrics

        return self._harvest_by_year(years, count_year, harvest_step)
