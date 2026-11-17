"""Phases du pipeline, dans l'ordre d'exécution, avec leur libellé et leurs attributs.

Chaque phase appartient à un bloc (`Block`). Les enrichissements viennent en dernier. Chacun est indépendant des autres. `fetch_missing` et `dois`, placées avant eux, lisent les relations au run suivant.
"""

from dataclasses import replace

from pipeline.graph import Block, Phase, Task
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
from pipeline.transformation.dois import dois
from pipeline.transformation.persons import persons
from pipeline.transformation.publications import notices, publications, relations, retractions
from pipeline.transformation.publications.author_grouping import author_grouping
from pipeline.transformation.publications.correction import metadata_correction
from pipeline.transformation.publications.subjects import subjects
from pipeline.transformation.publishing import publishing
from pipeline.transformation.structures import affiliations
from pipeline.transformation.structures.perimeter import (
    check_extraction_perimeter,
    refresh_perimeter_structures,
)

PHASES: tuple[Phase, ...] = (
    Phase(
        "harvest",
        "Moissonnage par affiliation",
        harvest.TASKS,
        Block.COLLECTION,
        check=check_extraction_perimeter,
        assemble=harvest.assemble,
    ),
    Phase(
        "harvest_by_person",
        "Moissonnage par personne",
        harvest_by_person.TASKS,
        Block.COLLECTION,
        when=lambda ctx: ctx.options.policy.harvest_by_person,
    ),
    Phase(
        "fetch_missing",
        "Recherche des documents trouvés dans une autre source",
        fetch_missing.STEPS,
        Block.COLLECTION,
        assemble=fetch_missing.assemble,
    ),
    Phase(
        "fetch_stale",
        "Recherche des documents non revus par le moissonnage",
        fetch_stale.TASKS,
        Block.COLLECTION,
        when=lambda ctx: ctx.options.policy.fetch_stale,
        assemble=fetch_stale.assemble,
    ),
    Phase(
        "fetch_truncated",
        "Complétion des listes d'auteurs OpenAlex tronquées",
        fetch_truncated.TASKS,
        Block.COLLECTION,
    ),
    Phase(
        "normalize",
        "Normalisation des documents bruts",
        normalize.STEPS,
        Block.SOURCE_RECORDS,
        assemble=normalize.assemble,
    ),
    Phase(
        "affiliations",
        "Structures, pays et périmètre des contributions sources",
        affiliations.STEPS,
        Block.SOURCE_RECORDS,
        check=check_extraction_perimeter,
        assemble=affiliations.assemble,
    ),
    Phase(
        "dois",
        "Référentiel des DOI",
        dois.TASKS,
        Block.SOURCE_RECORDS,
        assemble=dois.assemble,
    ),
    Phase(
        "publishing",
        "Référentiels de l'édition",
        publishing.STEPS,
        Block.SOURCE_RECORDS,
        assemble=publishing.assemble,
    ),
    Phase(
        "metadata_correction",
        "Correction des enregistrements sources",
        metadata_correction.TASKS,
        Block.SOURCE_RECORDS,
        assemble=metadata_correction.assemble,
    ),
    Phase(
        "publications",
        "Rattachement des enregistrements sources aux publications",
        publications.TASKS,
        Block.ENTITIES,
    ),
    Phase(
        "author_grouping",
        "Alignement des auteurs d'une publication entre ses sources",
        author_grouping.TASKS,
        Block.ENTITIES,
        assemble=author_grouping.assemble,
    ),
    Phase(
        "persons",
        "Rattachement des contributions aux personnes",
        persons.TASKS,
        Block.ENTITIES,
        assemble=persons.assemble,
    ),
    Phase(
        "finalize",
        "Données dérivées : périmètre des publications, purges, vues, compteurs",
        finalize.STEPS,
        Block.DERIVED_DATA,
        assemble=finalize.assemble,
    ),
    Phase(
        "relations",
        "Relations entre publications, indicateur « Rétracté »",
        relations.TASKS + notices.TASKS + retractions.TASKS,
        Block.ENRICHMENTS,
    ),
    Phase(
        "subjects",
        "Sujets des publications",
        subjects.TASKS,
        Block.ENRICHMENTS,
    ),
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
"""Matérialisation des structures des périmètres, exécutée par l'orchestrateur avant toute phase."""


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
