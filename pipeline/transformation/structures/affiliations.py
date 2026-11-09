"""Phase `affiliations` : structures, pays et indices de périmètre des contributions sources.

La phase s'arrête en échec si le périmètre d'extraction ne contient aucune structure. Ses tâches (`pipeline.graph`) ont chacune leur transaction :

1. **Référentiel ROR** (`affiliations.refresh_ror`) : importe la dernière version du dump ROR, si elle reste à importer.
2. **Référentiel des structures HAL** (`affiliations.refresh_hal_structures`) : charge les structures HAL citées et absentes du référentiel.
3. **Origine des adresses** (`affiliations.classify_addresses`) : classe le texte des adresses sans origine en adresse brute, libellé HAL ou nom seul.
4. **Résolution des adresses** (`affiliations.resolve_addresses`) : rattache les adresses aux structures connues.
5. **Partenaires de thèse** (`affiliations.resolve_thesis_partners`) : rattache aux structures les PPN des laboratoires partenaires de thèse.
6. **Pays** (`pipeline.transformation.countries.countries`) : pays des adresses, puis des contributions sources, des enregistrements sources et des publications.
7. **Contributions sources du périmètre** (`affiliations.populate`) : pose sur chaque contribution source les indices de son entrée dans le périmètre, d'après les structures atteintes et les identifiants des personnes à fiche RH.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import cast

from sqlalchemy import Connection

from infrastructure.read_models.perimeters.queries import (
    get_persons_structure_ids_list,
)
from pipeline.graph import Step, Task, in_transaction
from pipeline.http.polite_pool import default_user_agent
from pipeline.ingestion.complements.ror import ZenodoRorDumpSource
from pipeline.ingestion.hal.api import HalStructuresClient
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import LAST_BRANCH, inflect, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import waiting
from pipeline.transformation.countries import countries
from pipeline.transformation.structures.address_origin import classify_addresses
from pipeline.transformation.structures.address_resolution import (
    run_resolution,
)
from pipeline.transformation.structures.hal_structures import (
    HalStructureStore,
    run_refresh_hal_structures,
)
from pipeline.transformation.structures.idref_resolution import resolve_thesis_partners
from pipeline.transformation.structures.perimeter_evidence import (
    InPerimeterSyncCounts,
    refresh_source_contribution_structures,
    sync_perimeter_evidence,
)
from pipeline.transformation.structures.ror import RorStore, run_refresh_ror


def _resolve_addresses(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        perimeter_ids = set(get_persons_structure_ids_list(conn))
        stats = run_resolution(conn, perimeter_ids, ctx.logger)
    metrics = PhaseMetrics()
    metrics.add(seen=stats.processed)
    metrics.details["summary"] = {
        "adresses": stats.processed,
        "in_perimeter": stats.in_perimeter,
    }
    return metrics


def _resolve_thesis_partners(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        resolve_thesis_partners(conn, ctx.logger)
    return PhaseMetrics()


def _populate(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        perimeter_ids = set(get_persons_structure_ids_list(conn))
        counts = populate(conn, ctx.logger, perimeter_ids)
    metrics = PhaseMetrics()
    metrics.details["summary"] = {
        "source_contributions_entered": counts.added,
        "source_contributions_left": counts.removed,
    }
    return metrics


def populate(
    conn: Connection, logger: logging.Logger, perimeter_ids: set[int]
) -> InPerimeterSyncCounts:
    """Pose sur les contributions sources les indices de leur entrée dans le périmètre. Renvoie le nombre d'entrées et de sorties du périmètre. L'appelant commite."""
    with waiting(f"{LAST_BRANCH}rattachement en cours", logger) as line:
        refresh_source_contribution_structures(conn)
        counts = sync_perimeter_evidence(conn, perimeter_ids=list(perimeter_ids))
        entered = quantity(
            counts.added, "contribution source entrée", "contributions sources entrées"
        )
        left = f"{counts.removed} {inflect(counts.removed, 'sortie')}"
        line.conclude(f"{LAST_BRANCH}{entered} dans le périmètre, {left}")
    return counts


def _refresh_hal_structures(ctx: PhaseContext) -> PhaseMetrics:
    """Charge le référentiel des structures HAL."""
    with ctx.open_tx() as conn:
        return run_refresh_hal_structures(
            conn,
            source=HalStructuresClient(),
            store=HalStructureStore(conn),
            logger=ctx.logger,
            refresh_stale=ctx.options.policy.refresh_hal_structures,
        )


def _refresh_ror(ctx: PhaseContext) -> PhaseMetrics:
    """Rafraîchit le référentiel ROR depuis le dump publié sur Zenodo."""
    # Le dump est public : l'adresse du polite pool est facultative.
    source = ZenodoRorDumpSource(user_agent=default_user_agent(), logger=ctx.logger)
    with ctx.open_tx() as conn:
        return run_refresh_ror(conn, source=source, store=RorStore(conn), logger=ctx.logger)


_REFRESH_ROR = Task(
    "refresh_ror",
    reads=("ror_dump_imports", "source_contribution_rors"),
    writes=(
        "ror_organizations",
        "ror_relations",
        "ror_dump_imports",
        # Dépendants d'une organisation qui change de pays.
        "source_contribution_countries_queue",
    ),
    previous_run=("ror_dump_imports",),
    network="zenodo",
    run=_refresh_ror,
)


_REFRESH_HAL_STRUCTURES = Task(
    "refresh_hal_structures",
    reads=("source_contribution_hal_structures",),
    writes=(
        "hal_structures",
        "hal_structure_relations",
        "hal_structure_aliases",
        # Contributions sources d'une structure qui change de pays.
        "source_contribution_countries_queue",
    ),
    previous_run=("hal_structures", "hal_structure_aliases"),
    network="hal",
    run=_refresh_hal_structures,
)


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
    previous_run=("addresses.origin",),
    run=in_transaction(classify_addresses),
    section="Origine des adresses",
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
    previous_run=("addresses",),
    run=_resolve_addresses,
    section="Identification des structures dans les adresses institutionnelles",
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
    previous_run=("idref_structures",),
    run=_resolve_thesis_partners,
)


_POPULATE = Task(
    "populate",
    reads=(
        "address_structures",
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
    previous_run=(
        "source_records.publication_id",
        "person_identifiers",
        "source_contributions.neutralized_identifiers",
        "aligned_source_contributions",
    ),
    run=_populate,
    section="Rattachement des structures aux auteurs des documents",
)


STEPS = (
    Step(
        "structures",
        "adresses, identifiants ROR et HAL, partenaires de thèse → structures des contributions sources",
        (
            Step(
                "referentials",
                "dump ROR, structures HAL citées → référentiels ROR et HAL à jour",
                (_REFRESH_ROR, _REFRESH_HAL_STRUCTURES),
            ),
            _CLASSIFY_ADDRESSES,
            _RESOLVE_ADDRESSES,
            _RESOLVE_THESIS_PARTNERS,
        ),
    ),
    countries.STEP,
    _POPULATE,
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie les métriques de la résolution des adresses, avec les détails des deux référentiels, l'entonnoir des pays des adresses, et les entrées et sorties du périmètre."""
    metrics = by_task["resolve_addresses"]
    metrics.details.update(by_task["refresh_ror"].details)
    metrics.details.update(by_task["refresh_hal_structures"].details)
    metrics.details["summary"] = {
        **cast("dict[str, int]", metrics.details["summary"]),
        **countries.funnel(by_task),
        **cast("dict[str, int]", by_task["populate"].details["summary"]),
    }
    return metrics
