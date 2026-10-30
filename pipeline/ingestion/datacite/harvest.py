"""Moissonnage DataCite : tâche `harvest.datacite`.

La requête `GET /dois` cible, année par année, les affiliations de créateurs (`creators.affiliation.name`) contenant l'un des mots-clés du périmètre de moissonnage. La pagination suit un curseur. La phase `affiliations` détermine ensuite les contributions sources du périmètre.

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

    keywords: list[str]
    """Mots-clés cherchés dans les affiliations des créateurs."""


def build_query(year: int, keywords: list[str]) -> str:
    """Construit la requête `query` DataCite : DOI publiés l'année `year`, à affiliation de créateur contenant l'un des mots-clés, chacun cherché comme expression exacte."""
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
    """Moissonnage DataCite, année par année, des DOI à affiliation de créateur contenant un mot-clé du périmètre.

    Une erreur sur une année est journalisée, et le moissonnage passe à la suivante.
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
                # Le moissonnage de l'année rencontre la même erreur et la signale.
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
