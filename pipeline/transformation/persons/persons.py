"""Phase `persons` : homonymes des personnes rejetées (`homonyms`), rattachement des contributions aux personnes (`contribution_resolution`), formes de nom (`populate_person_name_forms`), puis purge (`purge`). Chaque tâche a sa transaction."""

from __future__ import annotations

from collections.abc import Mapping

from pipeline.graph import Block, Phase, Task
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import waiting
from pipeline.transformation.persons.contribution_resolution import resolve_contributions
from pipeline.transformation.persons.homonyms import attach_homonyms
from pipeline.transformation.persons.metrics import build_metrics
from pipeline.transformation.persons.populate_person_name_forms import populate
from pipeline.transformation.persons.purge import purge


def _attach_homonyms(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        counts = attach_homonyms(conn)
    ctx.logger.info(
        "%s%s, %s",
        BRANCH,
        quantity(
            counts["homonym_contributions_attached"],
            "contribution rattachée",
            "contributions rattachées",
        ),
        quantity(counts["homonym_contributions_released"], "détachée"),
    )
    ctx.logger.info(
        "%s%s, %s",
        LAST_BRANCH,
        quantity(counts["homonyms_created"], "homonyme créé", "homonymes créés"),
        quantity(counts["homonyms_deleted"], "supprimé"),
    )
    return PhaseMetrics(extras=counts)


def _resolve_contributions(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        counts = resolve_contributions(conn, ctx.logger, rebuild=ctx.options.rebuild_persons)
    return PhaseMetrics(extras=counts)


def _populate(ctx: PhaseContext) -> PhaseMetrics:
    with (
        ctx.open_tx() as conn,
        waiting(f"{BRANCH}rafraîchissement en cours", ctx.logger) as line,
    ):
        counts = populate(conn)
        line.erase()
    report = (
        f"{quantity(counts.inserted, 'forme ajoutée', 'formes ajoutées')},"
        f" {quantity(counts.updated, 'modifiée')}, {quantity(counts.deleted, 'supprimée')}"
    )
    return PhaseMetrics(extras=counts._asdict(), report=report)


def _purge(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        counts = purge(conn)
    ctx.logger.info(
        "%s%s à redécider (nom devenu ambigu)",
        BRANCH,
        quantity(counts["ambiguous_marked"], "contribution"),
    )
    ctx.logger.info(
        "%s%s",
        BRANCH,
        quantity(
            counts["deleted_attributions"],
            "attribution d'identifiant supprimée",
            "attributions d'identifiant supprimées",
        ),
    )
    ctx.logger.info(
        "%s%s %s",
        LAST_BRANCH,
        quantity(counts["deleted_persons"], "personne"),
        inflect(counts["deleted_persons"], "supprimée"),
    )
    return PhaseMetrics(extras=dict(counts))


_TIE_BREAK_READS = (
    "contributions.resolution_mode",
    "source_contribution_structures",
    "structures.structure_type",
    "source_contribution_hal_structures",
    "hal_structures",
    "publications.serial_id",
    "publications.publication_year",
)
"""Données lues par le départage d'une forme de nom ambiguë (`decide_with_tie_break`)."""

_TIE_BREAK_PREVIOUS_RUN = ("publications.serial_id", "publications.publication_year")
"""Données du départage écrites au run précédent : publications supprimées par `finalize.purge_publications`."""


_CHILDREN = (
    Task(
        "attach_homonyms",
        reads=(
            "rejected_contributions",
            "source_records.publication_id",
            "persons",
            "contributions.id",
            "contributions.publication_id",
            "contributions.person_id",
            "contributions.resolution_mode",
            "aligned_source_contributions",
            "source_contributions.contributor_information_id",
            "contributor_information",
        ),
        writes=(
            "persons",
            "person_name_forms",
            "contributions.person_id",
            "contributions.resolution_mode",
        ),
        # Personnes et contributions vidées par `purge_persons` ; contributions et alignements supprimés, enregistrements sources détachés par `finalize.purge_publications`.
        previous_run=(
            "persons",
            "contributions",
            "aligned_source_contributions",
            "source_records.publication_id",
        ),
        run=_attach_homonyms,
        section="Homonymes des personnes rejetées",
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
            "contributions.roles",
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
            *_TIE_BREAK_READS,
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
            # Formes de nom régénérées par `populate_person_name_forms` ; personnes, identifiants et formes supprimés, contributions vidées et marquées par `purge_persons`.
            "person_identifiers",
            "person_name_forms",
            "persons",
            "contributions",
            "contribution_resolution_queue",
            # Contributions et alignements supprimés, enregistrements sources détachés par `finalize.purge_publications`.
            "aligned_source_contributions",
            "source_records.publication_id",
            *_TIE_BREAK_PREVIOUS_RUN,
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
        # Contributions vidées et personnes supprimées par `purge_persons` ; alignements supprimés par `finalize.purge_publications`.
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
        "purge_persons",
        reads=(
            "contributions.publication_id",
            "contributions.person_id",
            "contributions.perimeter_evidence",
            # Une contribution des seuls rôles sans création de personne laisse supprimer sa personne.
            "contributions.roles",
            "aligned_source_contributions",
            "source_contributions.contributor_information_id",
            "source_contributions.neutralized_identifiers",
            "source_contributions.in_perimeter",
            "source_records.publication_id",
            "contributor_information",
            "person_name_forms",
            "person_identifiers",
            "persons",
            "hr_records",
            "confirmed_source_contributions",
            "rejected_contributions",
            "distinct_persons",
            *_TIE_BREAK_READS,
        ),
        # La suppression d'une personne emporte ses formes de nom et vide ses contributions ; une contribution rattachée par le nom dont la décision change est marquée pour la redécision de sa personne.
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
            *_TIE_BREAK_PREVIOUS_RUN,
        ),
        run=_purge,
        section="Purge des personnes",
    ),
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie les métriques de la phase, d'après les décomptes de ses tâches."""
    return build_metrics(
        homonyms=by_task["attach_homonyms"].extras,
        resolution=by_task["resolve_contributions"].extras,
        name_forms=by_task["populate_person_name_forms"].extras,
        purge=by_task["purge_persons"].extras,
    )


PHASE = Phase(
    "persons",
    "Rattachement des contributions aux personnes",
    _CHILDREN,
    Block.ENTITIES,
    assemble=assemble,
)
