"""Phase `affiliations` : structures et indices de périmètre des contributions sources.

La phase s'arrête en échec si le périmètre d'extraction ne contient aucune structure. Ses tâches (`pipeline.graph`) ont chacune leur transaction :

1. **Origine des adresses** (`affiliations.classify_addresses`) : classe le texte des adresses sans origine en adresse brute, libellé HAL ou nom seul.
2. **Adresses concaténées** (`affiliations.detect_concatenated_addresses`) : repère parmi les adresses non examinées celles qui réunissent plusieurs affiliations, chacune suivie des initiales de ses auteurs. Une adresse concaténée est sans indice de périmètre.
3. **Résolution des adresses** (`affiliations.resolve_addresses`) : rattache les adresses aux structures connues.
4. **Partenaires de thèse** (`affiliations.resolve_thesis_partners`) : rattache aux structures les PPN des laboratoires partenaires de thèse.
5. **Contributions sources du périmètre** (`affiliations.decide_source_contribution_perimeter`) : pose sur chaque contribution source les indices de son entrée dans le périmètre, d'après les structures atteintes et les identifiants des personnes à fiche RH.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import cast

from sqlalchemy import Connection

from infrastructure.read_models.perimeters.queries import (
    get_persons_structure_ids_list,
)
from pipeline.graph import Block, Phase, Step, Task, in_transaction
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import BRANCH, inflect, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import waiting
from pipeline.transformation.structures.address_concatenation import detect_concatenated_addresses
from pipeline.transformation.structures.address_origin import classify_addresses
from pipeline.transformation.structures.address_resolution import (
    run_resolution,
)
from pipeline.transformation.structures.idref_resolution import resolve_thesis_partners
from pipeline.transformation.structures.perimeter import check_extraction_perimeter
from pipeline.transformation.structures.perimeter_evidence import (
    InPerimeterSyncCounts,
    refresh_source_contribution_structures,
    sync_perimeter_evidence,
)


def _resolve_addresses(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        perimeter_ids = set(get_persons_structure_ids_list(conn))
        stats = run_resolution(conn, perimeter_ids, ctx.logger)
    metrics = PhaseMetrics()
    metrics.add(seen=stats.processed)
    if stats.processed:
        metrics.report = (
            f"structures du périmètre identifiées dans {quantity(stats.in_perimeter, 'adresse')}"
            f" ({100 * stats.in_perimeter / stats.processed:.1f}%)"
        )
    metrics.details["summary"] = {
        "adresses": stats.processed,
        "in_perimeter": stats.in_perimeter,
    }
    return metrics


def _resolve_thesis_partners(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        resolved, partners = resolve_thesis_partners(conn)
    return PhaseMetrics(report=f"{resolved} laboratoires partenaires rattachés sur {partners}")


def _decide_source_contribution_perimeter(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        perimeter_ids = set(get_persons_structure_ids_list(conn))
        counts = decide_source_contribution_perimeter(conn, ctx.logger, perimeter_ids)
    entered = quantity(counts.added, "contribution source entrée", "contributions sources entrées")
    metrics = PhaseMetrics(
        report=f"{entered} dans le périmètre, {counts.removed} {inflect(counts.removed, 'sortie')}"
    )
    metrics.details["summary"] = {
        "source_contributions_entered": counts.added,
        "source_contributions_left": counts.removed,
    }
    return metrics


def decide_source_contribution_perimeter(
    conn: Connection, logger: logging.Logger, perimeter_ids: set[int]
) -> InPerimeterSyncCounts:
    """Pose sur les contributions sources les indices de leur entrée dans le périmètre. Renvoie le nombre d'entrées et de sorties du périmètre. L'appelant commite."""
    with waiting(f"{BRANCH}rattachement en cours", logger) as line:
        refresh_source_contribution_structures(conn)
        counts = sync_perimeter_evidence(conn, perimeter_ids=list(perimeter_ids))
        line.erase()
    return counts


_CLASSIFY_ADDRESSES = Task(
    "classify_addresses",
    reads=(
        "addresses.raw_text",
        "addresses.normalized_text",
        "addresses.origin",
        "hal_structures",
        "ror_organizations",
        "place_name_forms",
    ),
    writes=("addresses.origin",),
    previous_runs=("addresses.origin",),
    run=in_transaction(classify_addresses),
    section="Origine des adresses",
    silent_when_empty=True,
)


_DETECT_CONCATENATED_ADDRESSES = Task(
    "detect_concatenated_addresses",
    reads=("addresses.raw_text", "addresses.is_concatenated"),
    writes=("addresses.is_concatenated",),
    previous_runs=("addresses.is_concatenated",),
    run=in_transaction(detect_concatenated_addresses),
    section="Adresses concaténées",
    silent_when_empty=True,
)


_RESOLVE_ADDRESSES = Task(
    "resolve_addresses",
    reads=(
        "structure_name_forms",
        "structures",
        "addresses.id",
        "addresses.normalized_text",
        "address_structures",
    ),
    writes=("address_structures.id", "address_structures.matched_form_id"),
    previous_runs=("addresses",),
    run=_resolve_addresses,
    section="Identification des structures dans les adresses institutionnelles",
    silent_when_empty=True,
)


_RESOLVE_THESIS_PARTNERS = Task(
    "resolve_thesis_partners",
    reads=(
        "structure_name_forms",
        "structures",
        "source_records.source_extras",
        "idref_structures",
    ),
    writes=("idref_structures",),
    previous_runs=("idref_structures",),
    run=_resolve_thesis_partners,
    section="Identification des laboratoires partenaires de thèse",
)


_DECIDE_SOURCE_CONTRIBUTION_PERIMETER = Task(
    "decide_source_contribution_perimeter",
    reads=(
        "address_structures",
        "addresses.is_concatenated",
        "perimeter_structures",
        "config",
        "source_contribution_addresses",
        # Branches ROR, structure HAL et thèse de `source_contribution_structures`.
        "source_contribution_rors",
        "source_contribution_hal_structures",
        "hal_structures",
        "hal_structure_relations",
        "hal_structure_aliases",
        "structures.ror_id",
        "structures.api_ids",
        "source_records.source_extras",
        "source_contributions.roles",
        "idref_structures",
        "source_contributions.source_record_id",
        "source_records.publication_id",
        # Identifiants des personnes à fiche RH : `hr_record_source_contributions`.
        "hr_records",
        "person_identifiers",
        "rejected_contributions",
        "contributor_information",
        "source_contributions.contributor_information_id",
        "source_contributions.neutralized_identifiers",
        "source_contributions.source",
        "source_records.publication_year",
        # Contributions des contributions sources à indices modifiés, marquées pour la recomposition de leurs attributs.
        "aligned_source_contributions",
    ),
    writes=(
        "source_contribution_structures",
        "source_contributions.perimeter_evidence",
        "source_contributions.in_perimeter",
        "source_record_keys_queue",
        "contribution_attributes_queue",
    ),
    previous_runs=(
        "source_records.publication_id",
        "person_identifiers",
        "aligned_source_contributions",
    ),
    run=_decide_source_contribution_perimeter,
    section="Rattachement des structures aux auteurs des documents",
)


_CHILDREN = (
    Step(
        "structures",
        "adresses, identifiants ROR et HAL, partenaires de thèse → structures des contributions sources",
        (
            _CLASSIFY_ADDRESSES,
            _DETECT_CONCATENATED_ADDRESSES,
            _RESOLVE_ADDRESSES,
            _RESOLVE_THESIS_PARTNERS,
        ),
    ),
    _DECIDE_SOURCE_CONTRIBUTION_PERIMETER,
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie les métriques de la résolution des adresses, avec les entrées et sorties du périmètre."""
    metrics = by_task["resolve_addresses"]
    metrics.details["summary"] = {
        **cast("dict[str, int]", metrics.details["summary"]),
        **cast(
            "dict[str, int]", by_task["decide_source_contribution_perimeter"].details["summary"]
        ),
    }
    return metrics


PHASE = Phase(
    "affiliations",
    "Structures et périmètre des contributions sources",
    _CHILDREN,
    Block.SOURCE_RECORDS,
    check=check_extraction_perimeter,
    assemble=assemble,
)
