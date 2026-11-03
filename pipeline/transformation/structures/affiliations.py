"""Phase `affiliations` : rattachement des contributions sources aux structures du périmètre.

La phase s'arrête en échec si le périmètre d'extraction ne contient aucune structure. Ses tâches (`pipeline.graph`) ont chacune leur transaction :

1. **Référentiel ROR** (`affiliations.refresh_ror`) : importe la dernière version du dump ROR, si elle reste à importer.
2. **Référentiel des structures HAL** (`affiliations.refresh_hal_structures`) : charge les structures HAL citées et absentes du référentiel.
3. **Origine des adresses** (`affiliations.classify_addresses`) : classe le texte des adresses sans origine en adresse brute, libellé HAL ou nom seul.
4. **Résolution des adresses** (`affiliations.resolve_addresses`) : rattache les adresses aux structures connues.
5. **Partenaires de thèse** (`affiliations.resolve_thesis_partners`) : rattache aux structures les PPN des laboratoires partenaires de thèse.
6. **Contributions sources du périmètre** (`affiliations.populate`) : pose sur chaque contribution source les indices de son entrée dans le périmètre, d'après les structures atteintes et les identifiants des personnes à fiche RH.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping

from sqlalchemy import Connection

from infrastructure.read_models.perimeters.queries import (
    get_persons_structure_ids_list,
)
from pipeline.graph import Task
from pipeline.http.polite_pool import default_user_agent
from pipeline.ingestion.complements.ror import ZenodoRorDumpSource
from pipeline.ingestion.hal.api import HalStructuresClient
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import LAST_BRANCH
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import waiting
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
    refresh_source_contribution_structures,
    sync_perimeter_evidence,
)
from pipeline.transformation.structures.ror import RorStore, run_refresh_ror


def _classify_addresses(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        return classify_addresses(conn, ctx.logger)


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
        conn.commit()
    return PhaseMetrics()


def _populate(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        perimeter_ids = set(get_persons_structure_ids_list(conn))
        populate(conn, ctx.logger, perimeter_ids)
    return PhaseMetrics()


def populate(conn: Connection, logger: logging.Logger, perimeter_ids: set[int]) -> None:
    """Pose sur les contributions sources les indices de leur entrée dans le périmètre. L'appelant commite."""
    t0 = time.perf_counter()
    with waiting(f"{LAST_BRANCH}rattachement en cours", logger) as line:
        refresh_source_contribution_structures(conn)
        sync_perimeter_evidence(conn, perimeter_ids=list(perimeter_ids))
        line.conclude(f"{LAST_BRANCH}Terminé en {time.perf_counter() - t0:.1f}s")


def _refresh_hal_structures(ctx: PhaseContext) -> PhaseMetrics:
    """Charge le référentiel des structures HAL, sur sa propre connexion."""

    with ctx.open_tx() as conn:
        return run_refresh_hal_structures(
            conn,
            source=HalStructuresClient(),
            store=HalStructureStore(conn),
            logger=ctx.logger,
            refresh_stale=ctx.options.policy.refresh_hal_structures,
        )


def _refresh_ror(ctx: PhaseContext) -> PhaseMetrics:
    """Rafraîchit le référentiel ROR depuis le dump publié sur Zenodo, sur sa propre connexion."""

    # Le dump est public : l'adresse du polite pool est facultative.
    source = ZenodoRorDumpSource(user_agent=default_user_agent(), logger=ctx.logger)
    with ctx.open_tx() as conn:
        return run_refresh_ror(conn, source=source, store=RorStore(conn), logger=ctx.logger)


TASKS = (
    Task(
        "affiliations.refresh_ror",
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
    ),
    Task(
        "affiliations.refresh_hal_structures",
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
    ),
    Task(
        "affiliations.classify_addresses",
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
        run=_classify_addresses,
        section="Origine des adresses",
    ),
    Task(
        "affiliations.resolve_addresses",
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
    ),
    Task(
        "affiliations.resolve_thesis_partners",
        reads=(
            "structure_name_forms",
            "structures",
            "source_records.source_extras",
            "idref_structures",
        ),
        writes=("idref_structures",),
        previous_run=("idref_structures",),
        run=_resolve_thesis_partners,
    ),
    Task(
        "affiliations.populate",
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
    ),
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie les métriques de la résolution des adresses, avec les détails des deux référentiels."""
    metrics = by_task["affiliations.resolve_addresses"]
    metrics.details.update(by_task["affiliations.refresh_ror"].details)
    metrics.details.update(by_task["affiliations.refresh_hal_structures"].details)
    return metrics
