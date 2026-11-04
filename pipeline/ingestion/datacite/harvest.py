"""Moissonnage DataCite : tâche `harvest.datacite`.

La requête `GET /dois` cible, année par année, les affiliations de créateurs (`creators.affiliation.name`) contenant l'un des mots-clés du périmètre de moissonnage. La pagination suit un curseur. La phase `affiliations` détermine ensuite les contributions sources du périmètre.

Les paramètres de requête comprennent `RECORD_PARAMS` (`api.py`), comme ceux des phases `fetch_missing` et `fetch_stale`. Le lien `next` de la pagination les reprend.
"""

from __future__ import annotations

from sqlalchemy import Connection

from pipeline.ingestion.common.harvester import (
    HarvestWindow,
    SourceHarvester,
    stage_pages,
)
from pipeline.ingestion.datacite.api import DataciteClient
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress


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
    query = build_query(year, keywords)
    stage_pages(
        conn,
        metrics,
        "datacite",
        lambda next_url: client.fetch_page(query, next_url, str(year)),
        progress=progress,
    )


class DataciteHarvester(SourceHarvester[DataciteClient]):
    """Moissonnage DataCite, année par année, des DOI à affiliation de créateur contenant un mot-clé du périmètre.

    Une erreur sur une année est journalisée, et le moissonnage passe à la suivante.
    """

    SOURCE = "datacite"
    MISSING_API_IDS = "aucun mot-clé"

    def run(self, window: HarvestWindow) -> PhaseMetrics:
        keywords = self._api_ids()
        client = self._client
        years = self._years(window)

        return self._harvest_by_year(
            years,
            lambda year: client.count(build_query(year, keywords), str(year)),
            lambda year, progress, metrics: harvest_year(
                client, self.conn, year, keywords, progress, metrics
            ),
        )
