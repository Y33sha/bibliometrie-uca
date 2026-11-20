"""Moissonnage theses.fr : tâche `harvest.theses`.

La recherche liste en une seule requête les thèses de l'ensemble des PPN d'établissement du périmètre, avec une pagination par `debut`. Elle retient les thèses soutenues dans la fenêtre d'années du run, et toutes les thèses en cours.

Le détail d'une thèse retenue est cherché seulement si elle est absente de `staging`, ou disparue de theses.fr. La tâche `fetch_stale.theses` cherche de nouveau le détail des autres thèses.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import Connection, text

from domain.types import as_int, as_mapping, as_sequence
from pipeline.ingestion.common.harvester import HarvestWindow, SourceHarvester
from pipeline.ingestion.common.lookup import LookupChannel, look_up, one_at_a_time
from pipeline.ingestion.theses.api import ThesesClient, fetch_thesis
from pipeline.ingestion.theses.fields import listed_id
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import Progress, track_progress

_STAGED_IDS_SQL = text(
    "SELECT source_id FROM staging WHERE source = 'theses' AND disappeared_at IS NULL"
)


def build_query(ppns: list[str], years: list[int]) -> str:
    """Construit la recherche theses.fr : thèses de l'un des PPN d'établissement de soutenance, soutenues dans l'intervalle `years` ou en cours."""
    soutenance = f"dateSoutenance:[{years[0]}-01-01 TO {years[-1]}-12-31]"
    return f"etabSoutenancePpn:({' OR '.join(ppns)}) AND ({soutenance} OR status:enCours)"


def list_theses(
    client: ThesesClient, ppns: list[str], progress: Progress, *, years: list[int]
) -> tuple[int, list[str]]:
    """Parcourt les thèses de la recherche, page après page. Renvoie le nombre de thèses annoncé par la recherche et les identifiants des thèses."""
    query = build_query(ppns, years)
    theses_ids: list[str] = []
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
            if theses_id:
                theses_ids.append(theses_id)
        start += len(theses)
        progress.advance(len(theses))

    return total or 0, theses_ids


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
                # La barre de la recherche et le bilan comptent déjà ces thèses.
                shown=False,
            ),
            theses_ids,
        )
    )


class ThesesHarvester(SourceHarvester[ThesesClient]):
    """Moissonnage theses.fr des thèses des établissements du périmètre."""

    SOURCE = "theses"
    MISSING_API_IDS = "aucun PPN d'établissement"
    DOCUMENT = "thèse"
    FEMININE = True

    def run(self, window: HarvestWindow) -> PhaseMetrics:
        years = self._years(window)
        scope = f"{years[0]}-{years[-1]}" if len(years) > 1 else str(years[0])
        with track_progress(None, self._label(scope), self.logger) as progress:
            seen, theses_ids = list_theses(self._client, self._api_ids(), progress, years=years)
        staged = staged_theses_ids(self.conn)
        metrics = stage_details(
            self.conn,
            self.logger,
            [theses_id for theses_id in theses_ids if theses_id not in staged],
        )
        metrics.seen = seen
        metrics.add(unchanged=sum(1 for theses_id in theses_ids if theses_id in staged))
        self._write_summary(metrics)
        return metrics
