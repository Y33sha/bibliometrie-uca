"""Phase `affiliations` : rattachement des contributions sources aux structures du périmètre.

La phase s'arrête en échec si le périmètre d'extraction ne contient aucune structure ; `run.py` matérialise `perimeter_structures` avant toute phase. Suivent quatre tâches (`pipeline.graph`), chacune dans sa propre transaction :

1. **Référentiel ROR** (tâche `affiliations.refresh_ror`) : importe la dernière version du dump ROR si elle n'est pas déjà importée (`pipeline.transformation.structures.ror`).
2. **Référentiel des structures HAL** (tâche `affiliations.refresh_hal_structures`) : charge les structures HAL citées et absentes du référentiel (`pipeline.transformation.structures.hal_structures`).
3. **Résolution des adresses** (tâche `affiliations.resolve_addresses`) : rattache les adresses aux structures connues (commits par lots), puis les PPN des laboratoires partenaires de thèse (tâche `affiliations.resolve_thesis_partners`).
4. **Contributions sources du périmètre** (tâche `affiliations.populate`) : pose les indices de l'entrée dans le périmètre (`perimeter_evidence`) sur les `source_contributions`, d'après les structures qu'elles atteignent (vue `source_contribution_structures`) et les identifiants des personnes qui ont une fiche RH.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection

from infrastructure.read_models.perimeters import (
    get_extraction_structure_ids,
    get_persons_structure_ids_list,
)
from pipeline.http.polite_pool import default_user_agent
from pipeline.ingestion.complements.ror import ZenodoRorDumpSource
from pipeline.ingestion.hal.api import HalStructuresClient
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.log_format import LAST_BRANCH
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import waiting
from pipeline.task_runner import TaskStep, run_tasks
from pipeline.transformation.structures.address_resolution import (
    run_resolution,
)
from pipeline.transformation.structures.hal_structures import (
    HalStructureStore,
    run_refresh_hal_structures,
)
from pipeline.transformation.structures.idref_resolution import resolve_thesis_partners
from pipeline.transformation.structures.perimeter import EmptyExtractionPerimeterError
from pipeline.transformation.structures.perimeter_evidence import (
    refresh_source_contribution_structures,
    sync_perimeter_evidence,
)
from pipeline.transformation.structures.ror import RorStore, run_refresh_ror


@dataclass(frozen=True)
class AffiliationsPhase:
    refresh_ror: Callable[[PhaseContext], PhaseMetrics]
    refresh_hal_structures: Callable[[PhaseContext, bool], PhaseMetrics]
    resolve_thesis_partners: Callable[[Connection, logging.Logger], int]

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Contrôle le périmètre d'extraction, exécute ses tâches et assemble les métriques de la phase."""
        with ctx.open_tx() as conn:
            if not get_extraction_structure_ids(conn):
                raise EmptyExtractionPerimeterError()

        by_task = run_tasks(
            "affiliations",
            {
                "affiliations.refresh_ror": TaskStep(lambda ctx, _breaker: self.refresh_ror(ctx)),
                "affiliations.refresh_hal_structures": TaskStep(
                    lambda ctx, _breaker: self.refresh_hal_structures(
                        ctx, ctx.options.policy.refresh_hal_structures
                    )
                ),
                "affiliations.resolve_addresses": TaskStep(
                    self._resolve_addresses,
                    section="Identification des structures dans les adresses institutionnelles",
                ),
                "affiliations.resolve_thesis_partners": TaskStep(self._resolve_thesis_partners),
                "affiliations.populate": TaskStep(
                    self._populate, section="Rattachement des structures aux auteurs des documents"
                ),
            },
            ctx,
        )
        metrics = by_task["affiliations.resolve_addresses"]
        metrics.details.update(by_task["affiliations.refresh_ror"].details)
        metrics.details.update(by_task["affiliations.refresh_hal_structures"].details)
        return metrics

    def _resolve_addresses(self, ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
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

    def _resolve_thesis_partners(self, ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
        with ctx.open_tx() as conn:
            self.resolve_thesis_partners(conn, ctx.logger)
            conn.commit()
        return PhaseMetrics()

    def _populate(self, ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
        with ctx.open_tx() as conn:
            perimeter_ids = set(get_persons_structure_ids_list(conn))
            populate(conn, ctx.logger, perimeter_ids)
        return PhaseMetrics()


# ── Contributions sources du périmètre ───────────────────────────────────


def populate(conn: Connection, logger: logging.Logger, perimeter_ids: set[int]) -> None:
    """Pose les indices de l'entrée dans le périmètre sur les `source_contributions` : rafraîchit la matview `source_contribution_structures`, puis synchronise `perimeter_evidence`. Le commit est à la charge de l'appelant."""
    t0 = time.perf_counter()
    with waiting(f"{LAST_BRANCH}rattachement en cours", logger) as line:
        refresh_source_contribution_structures(conn)
        sync_perimeter_evidence(conn, perimeter_ids=list(perimeter_ids))
        line.conclude(f"{LAST_BRANCH}Terminé en {time.perf_counter() - t0:.1f}s")


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    return AffiliationsPhase(
        refresh_ror=_run_refresh_ror,
        refresh_hal_structures=_run_refresh_hal_structures,
        resolve_thesis_partners=resolve_thesis_partners,
    )


def _run_refresh_hal_structures(ctx: PhaseContext, refresh_stale: bool) -> PhaseMetrics:
    """Chargement du référentiel des structures HAL, sur sa propre connexion."""

    with ctx.open_tx() as conn:
        return run_refresh_hal_structures(
            conn,
            source=HalStructuresClient(),
            store=HalStructureStore(conn),
            logger=ctx.logger,
            refresh_stale=refresh_stale,
        )


def _run_refresh_ror(ctx: PhaseContext) -> PhaseMetrics:
    """Rafraîchissement du référentiel ROR depuis le dump publié sur Zenodo, sur sa propre connexion."""

    # Le dump est public : l'adresse du polite pool y est facultative.
    source = ZenodoRorDumpSource(user_agent=default_user_agent(), logger=ctx.logger)
    with ctx.open_tx() as conn:
        return run_refresh_ror(conn, source=source, store=RorStore(conn), logger=ctx.logger)
