"""Moissonnage theses.fr : tâche `harvest.theses`.

Interroge en une seule requête l'ensemble des PPN d'établissement du périmètre, avec une pagination par `debut`. Sans année demandée, ramène tout l'historique theses.fr de ces établissements : la plage d'années de la configuration ne s'applique pas.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection

from domain.types import as_int, as_mapping, as_sequence
from infrastructure.read_models.perimeters import get_extraction_api_ids
from pipeline.ingestion.common.harvester import (
    HarvestConfigError,
    HarvestWindow,
    SourceHarvester,
    stage_document,
)
from pipeline.ingestion.theses.api import ThesesClient
from pipeline.ingestion.theses.fields import extract_doi, extract_id, is_ongoing
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress, track_progress


@dataclass(frozen=True)
class ThesesHarvestConfig:
    """Configuration du moissonnage theses.fr, lue en base."""

    # PPN des établissements de soutenance du périmètre d'extraction.
    ppns: list[str]


def build_query(ppns: list[str]) -> str:
    """Recherche theses.fr sur l'un des PPN d'établissement de soutenance."""
    return f"etabSoutenancePpn:({' OR '.join(ppns)})"


def harvest_theses(
    client: ThesesClient,
    conn: Connection,
    ppns: list[str],
    progress: Progress,
    *,
    year: int | None = None,
) -> PhaseMetrics:
    """Moissonne les thèses des établissements, page après page.

    Si `year` est fourni, retient les thèses soutenues cette année-là (NNT commençant par l'année) et toutes les thèses en cours. `progress` compte les thèses parcourues, et retient celles que le filtre garde. Le total des métriques porte sur toutes les thèses parcourues.
    """
    query = build_query(ppns)
    metrics = PhaseMetrics()
    total: int | None = None
    start = 0

    while total is None or start < total:
        data = client.fetch_page(query, start=start)
        if total is None:
            total = as_int(data.get("totalHits")) or 0
            progress.set_total(total)
            metrics.add(seen=total)
        theses = [as_mapping(t) for t in as_sequence(data.get("theses"))]
        if not theses:
            break

        for thesis in theses:
            theses_id = extract_id(thesis)
            if not theses_id:
                continue
            if year is not None and not is_ongoing(thesis) and not theses_id.startswith(str(year)):
                continue
            stage_document(
                conn,
                metrics,
                source="theses",
                source_id=theses_id,
                doi=extract_doi(thesis),
                raw_data=thesis,
            )
            progress.keep()

        conn.commit()
        start += len(theses)
        progress.advance(len(theses))

    return metrics


class ThesesHarvester(SourceHarvester[ThesesHarvestConfig, ThesesClient]):
    """Moissonnage theses.fr : les thèses des établissements du périmètre."""

    SOURCE = "theses"
    DOCUMENT = "thèse"
    FEMININE = True

    def load_config(self, conn: Connection) -> ThesesHarvestConfig:
        ppns = get_extraction_api_ids(conn, "theses")
        if not ppns:
            raise HarvestConfigError(
                "aucun PPN d'établissement (api_ids->'theses' vide pour le périmètre d'extraction)"
            )
        return ThesesHarvestConfig(ppns=ppns)

    def harvest_all(self, window: HarvestWindow, config: ThesesHarvestConfig) -> PhaseMetrics:
        # La colonne du périmètre reste vide sans `--year` : la barre s'aligne sur celles des autres sources.
        scope = str(window.year) if window.year is not None else ""
        with track_progress(
            None, self._label(scope), self.logger, count_kept=window.year is not None
        ) as progress:
            metrics = harvest_theses(
                self._client,
                self.conn,
                config.ppns,
                progress,
                year=window.year,
            )
        if window.year is None:
            self._write_summary(metrics)
        else:
            # Le filtre par année retient une partie des thèses parcourues ; le bilan porte sur celles-là.
            self._write_summary(metrics, found=metrics.new + metrics.updated + metrics.unchanged)
        return metrics
