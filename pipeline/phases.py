"""Phases du pipeline, dans l'ordre d'exécution. Le module de chaque phase la déclare (`PHASE`) : libellé, bloc, étapes et tâches, condition, précondition, métriques.

Chaque phase appartient à un bloc (`Block`). L'ordre suit les dépendances entre tâches. `fetch_missing` et `dois` lisent au run suivant les relations écrites par la phase `relations`.
"""

from dataclasses import replace

from pipeline.graph import Phase, Task
from pipeline.ingestion.common import (
    fetch_missing,
    fetch_stale,
    harvest,
    harvest_by_person,
    normalize,
)
from pipeline.ingestion.openalex import fetch_truncated
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation import finalize
from pipeline.transformation.countries import countries
from pipeline.transformation.dois import dois
from pipeline.transformation.persons import arbitration, persons
from pipeline.transformation.publications import open_access, publications
from pipeline.transformation.publications.author_grouping import author_grouping
from pipeline.transformation.publications.correction import metadata_correction
from pipeline.transformation.publications.relations import relations
from pipeline.transformation.publications.subjects import subjects
from pipeline.transformation.publishing import publishing
from pipeline.transformation.structures import affiliations, referentials
from pipeline.transformation.structures.perimeter import refresh_perimeter_structures

PHASES: tuple[Phase, ...] = (
    harvest.PHASE,
    harvest_by_person.PHASE,
    fetch_missing.PHASE,
    fetch_stale.PHASE,
    fetch_truncated.PHASE,
    normalize.PHASE,
    referentials.PHASE,
    dois.PHASE,
    publishing.PHASE,
    arbitration.PHASE,
    affiliations.PHASE,
    countries.PHASE,
    metadata_correction.PHASE,
    publications.PHASE,
    author_grouping.PHASE,
    persons.PHASE,
    finalize.PHASE,
    open_access.PHASE,
    relations.PHASE,
    subjects.PHASE,
)


def _refresh_perimeter_structures(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        refresh_perimeter_structures(conn)
    return PhaseMetrics()


PERIMETER_STRUCTURES = Task(
    "perimeter_structures",
    reads=("perimeters", "structure_parents", "structures"),
    writes=("perimeter_structures",),
    run=_refresh_perimeter_structures,
)
"""Matérialisation des structures des périmètres, exécutée par l'orchestrateur en tête de la première phase du run qui lit ses écritures."""


def _qualified(phase: str, task: Task) -> Task:
    """Renvoie la tâche, son nom et son groupe parallèle préfixés du nom de sa phase : `publishing.attach_serials`."""
    group = task.parallel_group
    return replace(
        task,
        name=f"{phase}.{task.name}",
        parallel_group=f"{phase}.{group}" if group is not None else None,
    )


ALL_TASKS: tuple[Task, ...] = (
    PERIMETER_STRUCTURES,
    *(_qualified(phase.name, task) for phase in PHASES for task in phase.tasks),
)
"""Tâches du pipeline dans l'ordre d'exécution, pour le graphe des dépendances : celle de l'orchestrateur, puis celles de chaque phase, préfixées du nom de leur phase."""
