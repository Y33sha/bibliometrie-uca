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


def _fetch_stale_fields(conn: Connection) -> dict[str, str]:
    return {"delai": quantity(delay(conn, ConfigKey.FETCH_STALE_AFTER_DAYS), "jour")}


PHASES: tuple[Phase, ...] = (
    Phase(
        "harvest",
        "Moissonnage par affiliation",
        phase_tasks("harvest"),
        harvesting=True,
        build=harvest.build,
    ),
    Phase(
        "harvest_by_person",
        "Moissonnage par personne",
        phase_tasks("harvest_by_person"),
        harvesting=True,
        build=harvest_by_person.build,
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
        phase_tasks("fetch_stale"),
        harvesting=True,
        label_fields=_fetch_stale_fields,
        build=fetch_stale.build,
    ),
    Phase(
        "fetch_truncated",
        "Re-téléchargement des documents OpenAlex tronqués à 100 auteurs",
        phase_tasks("fetch_truncated"),
        harvesting=True,
        build=fetch_truncated.build,
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
        phase_tasks("affiliations"),
        build=affiliations.build,
    ),
    Phase(
        "resolve_ra",
        "Résolution des agences d'enregistrement des DOI",
        resolve_ra.TASKS,
    ),
    Phase(
        "publishing",
        "Référentiels de l'édition",
        phase_tasks("publishing"),
        build=publishing.build,
    ),
    Phase(
        "metadata_correction",
        "Correction des métadonnées de publication",
        phase_tasks("metadata_correction"),
        build=metadata_correction.build,
    ),
    Phase(
        "publications",
        "Dédoublonnage des publications",
        phase_tasks("publications"),
        build=publications.build,
    ),
    Phase(
        "author_grouping",
        "Alignement des auteurs des enregistrements sources d'une même publication",
        phase_tasks("author_grouping"),
        build=author_grouping.build,
    ),
    Phase(
        "persons",
        "Résolution des personnes",
        phase_tasks("persons"),
        build=persons.build,
    ),
    Phase(
        "finalize",
        "Finalisation : périmètre des publications, vues des structures, purges et compteurs",
        phase_tasks("finalize"),
        build=finalize.build,
    ),
    Phase(
        "relations",
        "Relations entre publications apparentées",
        phase_tasks("relations"),
        extra=True,
        build=relations.build,
    ),
    Phase(
        "subjects",
        "Sujets des publications",
        phase_tasks("subjects"),
        extra=True,
        build=subjects.build,
    ),
    Phase(
        "countries",
        "Pays associés aux contributions sources",
        phase_tasks("countries"),
        extra=True,
        build=countries.build,
    ),
    Phase(
        "oa_status",
        "Statut open access des publications",
        phase_tasks("oa_status"),
        extra=True,
        build=oa_status.build,
    ),
)

ALL_TASKS: tuple[Task, ...] = (
    *phase_tasks(RUN_PHASE),
    *(task for phase in PHASES for task in phase.tasks),
)
"""Tâches du pipeline dans l'ordre d'exécution : celles de l'orchestrateur, puis celles de chaque phase."""
