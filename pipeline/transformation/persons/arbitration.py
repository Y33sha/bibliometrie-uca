"""Phase `identifier_arbitration` : arbitrage des identifiants de personne (`identifier_arbitration`), juste après la normalisation.

Les neutralisations écrites sont lues par le périmètre des contributions sources (phase `affiliations`), l'alignement des auteurs et le rattachement des contributions aux personnes.
"""

from __future__ import annotations

from collections.abc import Mapping

from pipeline.graph import Block, Phase, Task
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import BRANCH, inflect, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import waiting
from pipeline.transformation.persons.identifier_arbitration import arbitrate_identifier_conflicts


def _arbitrate_identifiers(ctx: PhaseContext) -> PhaseMetrics:
    with (
        ctx.open_tx() as conn,
        waiting(f"{BRANCH}en cours", ctx.logger) as line,
    ):
        counts = arbitrate_identifier_conflicts(conn)
        line.erase()
    neutralized = counts["neutralized"]
    report = (
        f"{quantity(neutralized, 'identifiant')} {inflect(neutralized, 'neutralisé')}"
        if neutralized
        else "rien à faire"
    )
    return PhaseMetrics(extras=counts, report=report)


ARBITRATE_IDENTIFIERS = Task(
    "arbitrate_identifiers",
    reads=(
        "contributor_information",
        "source_contributions.neutralized_identifiers",
        "source_contributions.contributor_information_id",
        "source_contributions.source",
        "source_contributions.source_record_id",
        # Les collectifs et les doublons d'auteur ne votent pas.
        "source_contributions.collective",
        "source_contributions.duplicate_of",
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
        # Contributions rattachées par un identifiant neutralisé, à redécider.
        "contribution_resolution_queue",
        "person_identifiers",
    ),
    previous_run=(
        # Doublons d'auteur repérés par l'alignement des auteurs.
        "source_contributions.duplicate_of",
        # Identifiants attribués et contributions rattachées par la phase `persons`.
        "person_identifiers",
        "contributions",
        # Contributions et alignements de l'alignement des auteurs ; rattachements des enregistrements sources par la phase `publications`.
        "aligned_source_contributions",
        "source_records.publication_id",
    ),
    run=_arbitrate_identifiers,
    label="Identifiants portés sous le nom d'une autre personne",
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie les métriques de la phase : identifiants neutralisés et contributions à redécider."""
    counts = by_task["arbitrate_identifiers"].extras
    metrics = PhaseMetrics(updated=counts.get("neutralized", 0))
    metrics.details["summary"] = {
        "identifiers_neutralized": counts.get("neutralized", 0),
        "marked_contributions": counts.get("marked_contributions", 0),
    }
    return metrics


PHASE = Phase(
    "identifier_arbitration",
    "Arbitrage des identifiants de personne",
    (ARBITRATE_IDENTIFIERS,),
    Block.SOURCE_RECORDS,
    assemble=assemble,
)
