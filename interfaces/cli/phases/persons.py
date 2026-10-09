"""Câblage de la phase `persons`."""

from __future__ import annotations

from application.pipeline.context import Phase
from infrastructure import PROJECT_ROOT
from infrastructure.observability.log import setup_file_logger


def build() -> Phase:
    """Rattachement des signatures aux personnes, et création des personnes inconnues.

    Une seule transaction enchaîne : la réapplication des épinglages posés par l'administration, la réinitialisation des attributions dérivées, le rattachement des signatures aux personnes connues, la création des personnes pour les signatures restantes, la régénération des formes de nom, puis la purge des formes devenues ambiguës et des personnes vidées. Les publications hors scope sont écartées (`domain/publications/scope`).

    Séquence, transaction et métriques dans `application/pipeline/persons/phase.py`.
    """
    from application.pipeline.persons.phase import PersonsPhase
    from infrastructure.pipeline.persons.matching import PgPersonsMatchingQueries
    from infrastructure.pipeline.persons.name_forms import PgPersonNameFormsQueries
    from infrastructure.repositories import authorship_repository, person_repository

    return PersonsPhase(
        PgPersonsMatchingQueries(),
        PgPersonNameFormsQueries(),
        person_repo_factory=person_repository,
        authorship_repo_factory=authorship_repository,
        orphans_log=setup_file_logger("persons_orphelines", str(PROJECT_ROOT / "logs")),
    )
