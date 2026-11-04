"""Phase `persons` : arbitrage des identifiants (`identifier_arbitration`), rattachement des contributions aux personnes (`contribution_resolution`), formes de nom (`populate_person_name_forms`), puis purge (`purge`). Chaque tâche a sa transaction."""

from __future__ import annotations

import time
from collections.abc import Mapping

from pipeline.graph import Task
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import LAST_BRANCH
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import waiting
from pipeline.transformation.persons.contribution_resolution import resolve_contributions
from pipeline.transformation.persons.identifier_arbitration import arbitrate_identifier_conflicts
from pipeline.transformation.persons.metrics import build_metrics
from pipeline.transformation.persons.populate_person_name_forms import populate
from pipeline.transformation.persons.purge import purge


def _arbitrate_identifiers(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        counts = arbitrate_identifier_conflicts(conn, ctx.logger)
    return PhaseMetrics(extras=counts)


def _resolve_contributions(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        counts = resolve_contributions(conn, ctx.logger)
    return PhaseMetrics(extras=counts)


def _populate(ctx: PhaseContext) -> PhaseMetrics:
    t0 = time.perf_counter()
    with (
        ctx.open_tx() as conn,
        waiting(f"{LAST_BRANCH}rafraîchissement en cours", ctx.logger) as line,
    ):
        counts = populate(conn)
        line.conclude(f"{LAST_BRANCH}Terminé en {time.perf_counter() - t0:.1f}s")
    return PhaseMetrics(extras=counts._asdict())


def _purge(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        counts = purge(conn)
    return PhaseMetrics(extras=dict(counts))


TASKS = (
    Task(
        "arbitrate_identifiers",
        reads=(
            "contributor_information",
            "source_contributions.neutralized_identifiers",
            "source_contributions.contributor_information_id",
            "source_contributions.source",
            "source_contributions.source_record_id",
            "source_records.publication_id",
            "contributions.id",
            "contributions.person_id",
            "contributions.resolution_mode",
            "aligned_source_contributions",
            "person_identifiers",
        ),
        writes=(
            "source_contributions.neutralized_identifiers",
            # Publications dont une contribution source change de neutralisation : leurs contributions sont à recalculer.
            "publication_contributions_queue",
            # Contributions rattachées par un identifiant neutralisé ou transféré, à redécider.
            "contribution_resolution_queue",
            "person_identifiers",
        ),
        previous_run=(
            # Identifiants attribués par `resolve_contributions` et supprimés par `purge` ; contributions rattachées par `resolve_contributions` et vidées par `purge`.
            "person_identifiers",
            "contributions",
            # Contributions et alignements supprimés, enregistrements sources détachés par `finalize.purge_publications`.
            "aligned_source_contributions",
            "source_records.publication_id",
        ),
        run=_arbitrate_identifiers,
    ),
    Task(
        "resolve_contributions",
        reads=(
            "contributions.id",
            "contributions.publication_id",
            "contributions.person_id",
            "aligned_source_contributions",
            "source_contributions.in_perimeter",
            "source_contributions.contributor_information_id",
            "source_contributions.neutralized_identifiers",
            "source_contributions.roles",
            "source_records.publication_id",
            "contributor_information",
            "confirmed_source_contributions",
            "rejected_contributions",
            "person_identifiers",
            "person_name_forms",
            "persons",
            # Personnes à fiche RH, dont la complétion des prénoms laisse le prénom tel quel.
            "hr_records",
            "contribution_resolution_queue",
        ),
        writes=(
            "contributions.person_id",
            "contributions.resolution_mode",
            "person_identifiers",
            "persons",
            "person_name_forms",
            # Marquages traités, retirés de la file.
            "contribution_resolution_queue",
        ),
        previous_run=(
            # Formes de nom régénérées par `populate` ; personnes, identifiants et formes supprimés, contributions vidées et marquées par `purge`.
            "person_identifiers",
            "person_name_forms",
            "persons",
            "contributions",
            "contribution_resolution_queue",
            # Contributions et alignements supprimés, enregistrements sources détachés par `finalize.purge_publications`.
            "aligned_source_contributions",
            "source_records.publication_id",
        ),
        run=_resolve_contributions,
        section="Identification des contributions",
    ),
    Task(
        "populate_person_name_forms",
        reads=(
            "persons",
            "contributions.person_id",
            "aligned_source_contributions",
            "source_contributions.source",
            "source_contributions.contributor_information_id",
            "contributor_information",
            "person_name_forms",
        ),
        writes=("person_name_forms",),
        # Contributions vidées et personnes supprimées par `purge` ; alignements supprimés par `finalize.purge_publications`.
        previous_run=(
            "persons",
            "person_name_forms",
            "contributions.person_id",
            "aligned_source_contributions",
        ),
        run=_populate,
        section="Rafraîchissement des formes de nom associées aux personnes",
    ),
    Task(
        "purge",
        reads=(
            "contributions.publication_id",
            "contributions.person_id",
            "contributions.resolution_mode",
            "contributions.perimeter_evidence",
            "aligned_source_contributions",
            "source_contributions.contributor_information_id",
            "source_contributions.neutralized_identifiers",
            "source_records.publication_id",
            "contributor_information",
            "person_name_forms",
            "person_identifiers",
            "persons",
            "hr_records",
            "confirmed_source_contributions",
            "rejected_contributions",
            "distinct_persons",
        ),
        # La suppression d'une personne emporte ses formes de nom et vide ses contributions ; une contribution à forme de nom ambiguë est marquée pour la redécision de sa personne.
        writes=(
            "contributions.person_id",
            "contributions.resolution_mode",
            "contribution_resolution_queue",
            "person_identifiers.id",
            "persons.id",
            "person_name_forms.id",
        ),
        # Contributions et alignements supprimés, enregistrements sources détachés par `finalize.purge_publications`.
        previous_run=(
            "contributions",
            "aligned_source_contributions",
            "source_records.publication_id",
        ),
        run=_purge,
    ),
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie les métriques de la phase, d'après les décomptes de ses tâches."""
    return build_metrics(
        resolution=by_task["resolve_contributions"].extras,
        arbitration=by_task["arbitrate_identifiers"].extras,
        name_forms=by_task["populate_person_name_forms"].extras,
        purge=by_task["purge"].extras,
    )
