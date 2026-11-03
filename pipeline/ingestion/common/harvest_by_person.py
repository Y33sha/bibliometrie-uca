"""Phase `harvest_by_person` : moissonnage des sources par les identifiants des personnes à fiche RH, vers `staging`.

Une tâche par source, en parallèle, sur la plage d'années du moissonnage ou la seule année `--year`. La phase est sautée dans un mode dont la policy l'exclut (`daily`). `--sources` restreint les sources.

Le profil de chaque source liste les types d'identifiant de personne acceptés (`domain/sources/registry.py`).
"""

from __future__ import annotations

from domain.sources.registry import PERSON_SEARCHED_SOURCES, Source, source_label
from pipeline.graph import TaskRun, task
from pipeline.ingestion.adapters import ADAPTERS
from pipeline.ingestion.common.harvester import HarvestWindow, run_harvest
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics


def _search(source: str) -> TaskRun:
    """Renvoie l'exécution de l'interrogation de `source` par les identifiants des personnes."""

    def run(ctx: PhaseContext) -> PhaseMetrics:
        window = HarvestWindow(start_year=ctx.options.start_year, year=ctx.options.year)
        harvester = ADAPTERS[Source(source)].person_harvester
        assert harvester is not None, f"{source} : source cherchée par personne sans moissonneur"
        return run_harvest(ctx, "harvest_by_person", source, harvester, window)

    return run


# Identifiants des personnes RH, posés par la phase `persons` au run précédent.
TASKS = tuple(
    task(
        f"harvest_by_person.{source}",
        reads=("config", "hr_records", "person_identifiers", "staging"),
        writes=("staging", "staging_normalization_queue"),
        previous_run=("staging", "person_identifiers"),
        network=source,
        parallel_group="harvest_by_person",
        run=_search(source),
        label=source_label(source),
        progress_bar=True,
        threshold=5,
        when=lambda ctx, source=source: source in ctx.options.sources,
    )
    for source in PERSON_SEARCHED_SOURCES
)
