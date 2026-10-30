"""Moissonnage theses.fr : tâche `harvest.theses`.

La recherche liste en une seule requête les thèses de l'ensemble des PPN d'établissement du périmètre, avec une pagination par `debut`. La requête ramène tout l'historique theses.fr de ces établissements. Le moissonnage retient les thèses soutenues dans la fenêtre d'années du run, et toutes les thèses en cours.

Le détail d'une thèse retenue est lu seulement si elle est absente de `staging`, ou disparue de theses.fr. La tâche `fetch_stale.theses` relit le détail des autres thèses.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import Connection, text

from domain.types import as_int, as_mapping, as_sequence
from infrastructure.read_models.perimeters.queries import get_extraction_api_ids
from pipeline.ingestion.common.harvester import HarvestConfigError, HarvestWindow, SourceHarvester
from pipeline.ingestion.common.lookup import LookupChannel, look_up, one_at_a_time
from pipeline.ingestion.theses.api import ThesesClient, fetch_thesis
from pipeline.ingestion.theses.fields import is_ongoing, listed_id
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress, track_progress

_STAGED_IDS_SQL = text(
    "SELECT source_id FROM staging WHERE source = 'theses' AND disappeared_at IS NULL"
)


@dataclass(frozen=True)
class ThesesHarvestConfig:
    """Configuration du moissonnage theses.fr, lue en base."""

    ppns: list[str]
    """PPN des établissements de soutenance du périmètre de moissonnage."""


def build_query(ppns: list[str]) -> str:
    """Construit la recherche theses.fr sur l'un des PPN d'établissement de soutenance."""
    return f"etabSoutenancePpn:({' OR '.join(ppns)})"


def list_theses(
    client: ThesesClient, ppns: list[str], progress: Progress, *, years: list[int]
) -> tuple[int, list[str]]:
    """Parcourt les thèses des établissements, page après page. Renvoie le nombre de thèses parcourues et les identifiants retenus.

    Sont retenues les thèses soutenues l'une des années `years` (NNT commençant par l'année), et toutes les thèses en cours. `progress` compte les thèses parcourues et les thèses retenues par le filtre.
    """
    prefixes = tuple(str(year) for year in years)
    query = build_query(ppns)
    kept: list[str] = []
    total: int | None = None
    start = 0

    while total is None or start < total:
        data = client.fetch_page(query, start=start)
        if total is None:
            total = as_int(data.get("totalHits")) or 0
            progress.set_total(total)
        theses = [as_mapping(t) for t in as_sequence(data.get("theses"))]
        if not theses:
            break
        for thesis in theses:
            theses_id = listed_id(thesis)
            if not theses_id:
                continue
            if not is_ongoing(thesis) and not theses_id.startswith(prefixes):
                continue
            kept.append(theses_id)
            progress.keep()
        start += len(theses)
        progress.advance(len(theses))

    return total or 0, kept


def staged_theses_ids(conn: Connection) -> set[str]:
    """Renvoie les identifiants des thèses présentes dans `staging`, hors thèses disparues de theses.fr."""
    return set(conn.execute(_STAGED_IDS_SQL).scalars())


def stage_details(conn: Connection, log: logging.Logger, theses_ids: list[str]) -> PhaseMetrics:
    """Lit le détail des thèses données et l'écrit dans `staging`. Une thèse listée par la recherche, au détail introuvable, reste hors de `staging`."""
    return asyncio.run(
        look_up(
            conn,
            log,
            LookupChannel(
                source="theses",
                fetch=one_at_a_time(fetch_thesis),
                on_absent=lambda conn, theses_id: None,
                stage=lambda staging, thesis: staging.stage("theses", thesis),
            ),
            theses_ids,
        )
    )


class ThesesHarvester(SourceHarvester[ThesesHarvestConfig, ThesesClient]):
    """Moissonnage theses.fr des thèses des établissements du périmètre."""

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
        years = self._years(window)
        scope = f"{years[0]}-{years[-1]}" if len(years) > 1 else str(years[0])
        with track_progress(None, self._label(scope), self.logger, count_kept=True) as progress:
            seen, kept = list_theses(self._client, config.ppns, progress, years=years)
        staged = staged_theses_ids(self.conn)
        metrics = stage_details(
            self.conn, self.logger, [theses_id for theses_id in kept if theses_id not in staged]
        )
        metrics.seen = seen
        metrics.add(unchanged=sum(1 for theses_id in kept if theses_id in staged))
        # Le filtre par année retient une partie des thèses parcourues ; le bilan compte seulement les thèses retenues.
        self._write_summary(metrics, found=metrics.new + metrics.updated + metrics.unchanged)
        return metrics
