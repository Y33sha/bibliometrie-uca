"""Moissonnage d'INSPIRE-HEP : tâche `harvest.inspire`.

La recherche cible, année par année, les fiches dont un auteur est affilié à une institution du périmètre de moissonnage. Une valeur numérique d'`api_ids` est un numéro d'institution INSPIRE (`affid`), une autre valeur un nom d'affiliation cherché en texte (`aff`). Le filtre `date` retient une fiche quand l'une de ses dates tombe dans l'année : publication, impression ou prépublication. La phase `affiliations` détermine ensuite les contributions sources du périmètre.
"""

from __future__ import annotations

from sqlalchemy import Connection

from pipeline.ingestion.common.harvester import (
    HarvestWindow,
    SourceHarvester,
    stage_pages,
)
from pipeline.ingestion.inspire.api import InspireClient
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress


def affiliation_clause(api_ids: list[str]) -> str:
    """Construit la condition d'affiliation : `affid:<numéro>` pour un numéro d'institution, `aff:"<nom>"` pour un nom, réunis par `or`."""
    clauses = [
        f"affid:{value}"
        if value.isdigit()
        else 'aff:"{}"'.format(value.replace("\\", "\\\\").replace('"', '\\"'))
        for value in (v.strip() for v in api_ids)
        if value
    ]
    return " or ".join(clauses)


def build_query(year: int, api_ids: list[str]) -> str:
    """Construit la requête INSPIRE : fiches d'un auteur affilié à l'une des institutions, datées de l'année `year`."""
    return f"({affiliation_clause(api_ids)}) and date {year}"


def harvest_year(
    client: InspireClient,
    conn: Connection,
    year: int,
    api_ids: list[str],
    progress: Progress,
    metrics: PhaseMetrics,
) -> None:
    """Moissonne les fiches d'une année, page après page, et les compte dans `metrics`."""
    query = build_query(year, api_ids)
    stage_pages(
        conn,
        metrics,
        "inspire",
        lambda next_url: client.fetch_page(query, next_url, str(year)),
        progress=progress,
    )


class InspireHarvester(SourceHarvester[InspireClient]):
    """Moissonnage d'INSPIRE-HEP, année par année, des fiches affiliées à une institution du périmètre.

    Une erreur sur une année est journalisée, et le moissonnage passe à la suivante.
    """

    SOURCE = "inspire"
    MISSING_API_IDS = "aucune institution"
    DOCUMENT = "fiche"
    FEMININE = True

    def run(self, window: HarvestWindow) -> PhaseMetrics:
        api_ids = self._api_ids()
        client = self._client
        years = self._years(window)

        return self._harvest_by_year(
            years,
            lambda year: client.count(build_query(year, api_ids), str(year)),
            lambda year, progress, metrics: harvest_year(
                client, self.conn, year, api_ids, progress, metrics
            ),
        )
