"""Phase `affiliations` : rattachement des signatures aux structures du périmètre.

La phase s'arrête en échec si le périmètre d'extraction ne contient aucune structure ; `run.py` matérialise `perimeter_structures` avant toute phase. Suivent quatre tâches (`pipeline.graph`), chacune dans sa propre transaction :

1. **Référentiel ROR** (tâche `affiliations.refresh_ror`) : importe la dernière version du dump ROR si elle n'est pas déjà importée (`pipeline.transformation.structures.ror`).
2. **Référentiel des structures HAL** (tâche `affiliations.refresh_hal_structures`) : charge les structures HAL citées et absentes du référentiel (`pipeline.transformation.structures.hal_structures`).
3. **Résolution des adresses** (tâche `affiliations.resolve_addresses`) : rattache les adresses aux structures connues (commits par lots), puis les PPN des laboratoires partenaires de thèse (tâche `affiliations.resolve_thesis_partners`).
4. **Signatures du périmètre** (tâche `affiliations.populate`) : pose les indices de l'entrée dans le périmètre (`perimeter_evidence`) sur les `source_authorships`, d'après les structures qu'elles atteignent (vue `source_authorship_structures`) et l'identité des personnes RH.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection

from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.libelles import DERNIERE_BRANCHE
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import attente
from pipeline.task_runner import TaskStep, run_tasks
from pipeline.transformation.structures.address_resolution import (
    AddressResolutionQueries,
    run_resolution,
)
from pipeline.transformation.structures.idref_resolution import resolve_thesis_partners
from pipeline.transformation.structures.perimeter import (
    EmptyExtractionPerimeterError,
    PerimeterQueries,
)
from pipeline.transformation.structures.perimeter_evidence import (
    refresh_source_authorship_structures,
    sync_perimeter_evidence,
)


@dataclass(frozen=True)
class AffiliationsPhase:
    address_queries: AddressResolutionQueries
    perimeter_queries: PerimeterQueries
    refresh_ror: Callable[[PhaseContext], PhaseMetrics]
    refresh_hal_structures: Callable[[PhaseContext, bool], PhaseMetrics]
    resolve_thesis_partners: Callable[[Connection, logging.Logger], int]

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Contrôle le périmètre d'extraction, exécute ses tâches et assemble les métriques de la phase."""
        with ctx.open_tx() as conn:
            if self.perimeter_queries.count_extraction_structures(conn) == 0:
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
            perimeter_ids = set(self.perimeter_queries.get_persons_structure_ids_list(conn))
            stats = run_resolution(conn, self.address_queries, perimeter_ids, ctx.logger)
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
            perimeter_ids = set(self.perimeter_queries.get_persons_structure_ids_list(conn))
            populate(conn, ctx.logger, perimeter_ids)
        return PhaseMetrics()


# ── Signatures du périmètre ───────────────────────────────────


def populate(conn: Connection, logger: logging.Logger, perimeter_ids: set[int]) -> None:
    """Pose les indices de l'entrée dans le périmètre sur les `source_authorships` : rafraîchit la matview `source_authorship_structures`, puis synchronise `perimeter_evidence`. Le commit est à la charge de l'appelant."""
    t0 = time.perf_counter()
    with attente(f"{DERNIERE_BRANCHE}rattachement en cours", logger) as ligne:
        refresh_source_authorship_structures(conn)
        sync_perimeter_evidence(conn, perimeter_ids=list(perimeter_ids))
        ligne.conclut(f"{DERNIERE_BRANCHE}Terminé en {time.perf_counter() - t0:.1f}s")


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    """Rattachement des signatures aux structures du périmètre."""
    from pipeline.transformation.structures.address_resolution import (
        AddressResolutionQueries,
    )
    from pipeline.transformation.structures.perimeter import PerimeterQueries

    return AffiliationsPhase(
        AddressResolutionQueries(),
        PerimeterQueries(),
        refresh_ror=_run_refresh_ror,
        refresh_hal_structures=_run_refresh_hal_structures,
        resolve_thesis_partners=resolve_thesis_partners,
    )


def _run_refresh_hal_structures(ctx: PhaseContext, refresh_stale: bool) -> PhaseMetrics:
    """Chargement du référentiel des structures HAL, sur sa propre connexion."""
    from pipeline.ingestion.hal.structures import HalStructuresClient
    from pipeline.transformation.structures.hal_structures import (
        HalStructuresQueries,
        run_refresh_hal_structures,
    )

    with ctx.open_tx() as conn:
        return run_refresh_hal_structures(
            conn,
            source=HalStructuresClient(),
            queries=HalStructuresQueries(conn),
            logger=ctx.logger,
            refresh_stale=refresh_stale,
        )


def _run_refresh_ror(ctx: PhaseContext) -> PhaseMetrics:
    """Rafraîchissement du référentiel ROR depuis le dump publié sur Zenodo, sur sa propre connexion."""
    from pipeline.http.polite_pool import build_user_agent, get_polite_pool_email_optional
    from pipeline.ingestion.ror.dump import ZenodoRorDumpSource
    from pipeline.transformation.structures.ror import RorDumpQueries, run_refresh_ror

    # Le dump est public : l'adresse du polite pool y est facultative.
    source = ZenodoRorDumpSource(
        user_agent=build_user_agent(get_polite_pool_email_optional() or ""), logger=ctx.logger
    )
    with ctx.open_tx() as conn:
        return run_refresh_ror(conn, source=source, repo=RorDumpQueries(conn), logger=ctx.logger)
