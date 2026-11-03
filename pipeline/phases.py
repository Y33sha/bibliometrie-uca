"""Phases du pipeline, dans l'ordre d'exécution, avec leur libellé et leurs attributs.

Les enrichissements (`extra`) viennent en dernier. Chacun est indépendant des autres. Des phases placées avant eux lisent leurs sorties au run suivant : `resolve_ra` et `fetch_missing` lisent les relations, `normalize` et `publications` les pays, `publications` le statut open access.
"""

from sqlalchemy import Connection

from domain.config import ConfigKey
from pipeline.graph import RUN_PHASE, Phase, Task, phase_tasks
from pipeline.ingestion.common import (
    fetch_missing,
    fetch_stale,
    harvest,
    harvest_by_person,
    normalize,
)
from pipeline.ingestion.openalex import fetch_truncated
from pipeline.runtime.config import delay
from pipeline.runtime.observability.log_format import quantity
from pipeline.transformation import finalize
from pipeline.transformation.countries import countries
from pipeline.transformation.persons import persons
from pipeline.transformation.publications import oa_status, publications, relations
from pipeline.transformation.publications.author_grouping import author_grouping
from pipeline.transformation.publications.correction import metadata_correction
from pipeline.transformation.publications.subjects import subjects
from pipeline.transformation.publishing import publishing, resolve_ra
from pipeline.transformation.structures import affiliations
from pipeline.transformation.structures.perimeter import check_extraction_perimeter


def _fetch_stale_fields(conn: Connection) -> dict[str, str]:
    return {"delai": quantity(delay(conn, ConfigKey.FETCH_STALE_AFTER_DAYS), "jour")}


PHASES: tuple[Phase, ...] = (
    Phase(
        "harvest",
        "Moissonnage par affiliation",
        harvest.TASKS,
        harvesting=True,
        check=check_extraction_perimeter,
        assemble=harvest.assemble,
    ),
    Phase(
        "harvest_by_person",
        "Moissonnage par personne",
        harvest_by_person.TASKS,
        harvesting=True,
        when=lambda options: options.policy.harvest_by_person,
    ),
    Phase(
        "fetch_missing",
        "Recherche dans chaque source des documents trouvés dans les autres",
        phase_tasks("fetch_missing"),
        harvesting=True,
        build=fetch_missing.build,
    ),
    Phase(
        "fetch_stale",
        "Recherche des documents non revus depuis {delai}",
        fetch_stale.TASKS,
        harvesting=True,
        label_fields=_fetch_stale_fields,
        when=lambda options: options.policy.fetch_stale,
        assemble=fetch_stale.assemble,
    ),
    Phase(
        "fetch_truncated",
        "Re-téléchargement des documents OpenAlex tronqués à 100 auteurs",
        fetch_truncated.TASKS,
        harvesting=True,
    ),
    Phase(
        "normalize",
        "Normalisation des données brutes",
        phase_tasks("normalize"),
        build=normalize.build,
    ),
    Phase(
        "affiliations",
        "Résolution des affiliations par contribution source",
        affiliations.TASKS,
        check=check_extraction_perimeter,
        assemble=affiliations.assemble,
    ),
    Phase(
        "resolve_ra",
        "Résolution des agences d'enregistrement des DOI",
        resolve_ra.TASKS,
    ),
    Phase(
        "publishing",
        "Référentiels de l'édition",
        publishing.TASKS,
        assemble=publishing.assemble,
    ),
    Phase(
        "metadata_correction",
        "Correction des métadonnées de publication",
        metadata_correction.TASKS,
        assemble=metadata_correction.assemble,
    ),
    Phase(
        "publications",
        "Dédoublonnage des publications",
        publications.TASKS,
    ),
    Phase(
        "author_grouping",
        "Alignement des auteurs des enregistrements sources d'une même publication",
        author_grouping.TASKS,
        assemble=author_grouping.assemble,
    ),
    Phase(
        "persons",
        "Résolution des personnes",
        persons.TASKS,
        assemble=persons.assemble,
    ),
    Phase(
        "finalize",
        "Finalisation : périmètre des publications, vues des structures, purges et compteurs",
        finalize.TASKS,
        assemble=finalize.assemble,
    ),
    Phase(
        "relations",
        "Relations entre publications apparentées",
        relations.TASKS,
        extra=True,
    ),
    Phase(
        "subjects",
        "Sujets des publications",
        subjects.TASKS,
        extra=True,
    ),
    Phase(
        "countries",
        "Pays associés aux contributions sources",
        countries.TASKS,
        extra=True,
        assemble=countries.assemble,
    ),
    Phase(
        "oa_status",
        "Statut open access des publications",
        oa_status.TASKS,
        extra=True,
        assemble=oa_status.assemble,
    ),
)

ALL_TASKS: tuple[Task, ...] = (
    *phase_tasks(RUN_PHASE),
    *(task for phase in PHASES for task in phase.tasks),
)
"""Tâches du pipeline dans l'ordre d'exécution : celles de l'orchestrateur, puis celles de chaque phase."""
