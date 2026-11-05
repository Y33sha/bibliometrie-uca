"""Moissonnage ScanR brevets : tâche `harvest.scanr_patents`.

La requête à l'index `scanr-patents` cible les familles dont un déposant a l'identifiant Paysage d'une structure du périmètre, année de premier dépôt par année. La pagination suit `search_after`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from domain.types import JsonValue
from pipeline.ingestion.common.harvester import HarvestWindow, SourceHarvester, stage_pages
from pipeline.ingestion.scanr.api import ScanrClient, hits_page, page_query, search_after
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress

EXCLUDED_FIELDS = ("publications", "denormalized_structures", "co_*", "title_abs_text")
"""Champs retirés des familles : articles cités par le brevet, et champs dérivés des autres champs pour le portail ScanR."""


def build_query(
    year: int,
    applicant_ids: list[str],
    search_after: Sequence[JsonValue] | None = None,
) -> Mapping[str, JsonValue]:
    """Construit la requête d'une page : familles de premier dépôt en `year`, dont un déposant a l'un des identifiants."""
    return page_query(
        [{"term": {"year": year}}, {"terms": {"applicants.ids.id.keyword": applicant_ids}}],
        search_after,
        excludes=EXCLUDED_FIELDS,
    )


class ScanrPatentsHarvester(SourceHarvester[ScanrClient]):
    """Moissonnage des familles de brevets déposées par les structures du périmètre, année par année."""

    SOURCE = "scanr_patents"
    MISSING_API_IDS = "aucun identifiant Paysage de déposant"
    DOCUMENT = "famille"
    FEMININE = True

    def run(self, window: HarvestWindow) -> PhaseMetrics:
        ids = self._api_ids()
        client = self._client

        def harvest_year(year: int, progress: Progress, metrics: PhaseMetrics) -> None:
            stage_pages(
                self.conn,
                metrics,
                self.SOURCE,
                lambda token: hits_page(
                    client.fetch_page(build_query(year, ids, search_after(token)))
                ),
                progress=progress,
            )

        return self._harvest_by_year(
            self._years(window), lambda year: client.count(build_query(year, ids)), harvest_year
        )
