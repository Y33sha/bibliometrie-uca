"""Moissonnage theses.fr : tâche `harvest.theses`.

Interroge en une seule requête l'ensemble des PPN d'établissement du périmètre, avec une pagination par `debut`. Sans année demandée, ramène tout l'historique theses.fr de ces établissements : la plage d'années de la configuration ne s'applique pas.
"""

from __future__ import annotations

from collections.abc import Callable
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
from pipeline.runtime.observability.logging_scope import ScopedOrPlainLogger, scoped_logger
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import Progression, progression


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
    logger: ScopedOrPlainLogger,
    avancement: Progression,
    *,
    year: int | None = None,
    breaker_tripped: Callable[[], bool] = lambda: False,
) -> PhaseMetrics:
    """Moissonne les thèses des établissements, page après page.

    Si `year` est fourni, retient les thèses soutenues cette année-là (NNT commençant par l'année) et toutes les thèses en cours. `avancement` compte les thèses parcourues, et retient celles que le filtre garde. Le total des métriques porte sur toutes les thèses parcourues.
    """
    query = build_query(ppns)
    metrics = PhaseMetrics()
    total: int | None = None
    debut = 0

    while total is None or debut < total:
        if breaker_tripped():
            logger.warning(
                "à bout (429/5xx répétés) — pagination interrompue (retry au prochain run)"
            )
            break
        data = client.fetch_page(query, debut=debut)
        if total is None:
            total = as_int(data.get("totalHits")) or 0
            avancement.fixer_total(total)
            metrics.add(seen=total)
        theses = [as_mapping(t) for t in as_sequence(data.get("theses"))]
        if not theses:
            break

        for these in theses:
            theses_id = extract_id(these)
            if not theses_id:
                continue
            if year is not None and not is_ongoing(these) and not theses_id.startswith(str(year)):
                continue
            stage_document(
                conn,
                metrics,
                source="theses",
                source_id=theses_id,
                doi=extract_doi(these),
                raw_data=these,
            )
            avancement.retient()

        conn.commit()
        debut += len(theses)
        avancement.avance(len(theses))

    return metrics


class ThesesHarvester(SourceHarvester[ThesesHarvestConfig, ThesesClient]):
    """Moissonnage theses.fr : les thèses des établissements du périmètre."""

    SOURCE = "theses"
    DOCUMENT = "thèse"
    FEMININ = True

    def load_config(self, conn: Connection) -> ThesesHarvestConfig:
        ppns = get_extraction_api_ids(conn, "theses")
        if not ppns:
            raise HarvestConfigError(
                "aucun PPN d'établissement (api_ids->'theses' vide pour le périmètre d'extraction)"
            )
        return ThesesHarvestConfig(ppns=ppns)

    def harvest_all(self, window: HarvestWindow, config: ThesesHarvestConfig) -> PhaseMetrics:
        # La colonne du périmètre reste vide sans `--year` : la barre s'aligne sur celles des autres sources.
        portee = str(window.year) if window.year is not None else ""
        with progression(
            None, self._libelle(portee), self.logger, compte_retenus=window.year is not None
        ) as avancement:
            metrics = harvest_theses(
                self._client,
                self.conn,
                config.ppns,
                scoped_logger(self.logger, self.SOURCE),
                avancement,
                year=window.year,
                breaker_tripped=self._breaker_tripped,
            )
        if window.year is None:
            self._ecrit_bilan(metrics)
        else:
            # Le filtre par année retient une partie des thèses parcourues ; le bilan porte sur celles-là.
            self._ecrit_bilan(metrics, trouves=metrics.new + metrics.updated + metrics.unchanged)
        return metrics
