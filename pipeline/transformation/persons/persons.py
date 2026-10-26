"""Orchestrateur unique de la phase personnes.

Quatre tâches (`pipeline.graph`), chacune sur sa transaction :

1. **arbitrate_identifiers** — neutralise les identifiants mal placés d'après le consensus de nom de leurs porteurs, puis tranche les conflits d'attribution par le vote des contributions. Les contributions rattachées par un identifiant neutralisé ou transféré sont marquées pour la redécision de leur personne (`pipeline.transformation.persons.identifier_arbitration`).
2. **resolve_contributions** — applique les épinglages aux contributions, complète les prénoms réduits, puis rattache les contributions sans personne à une personne existante, ou à une personne créée de leur nom (`pipeline.transformation.persons.contribution_resolution`).
3. **populate** — régénère les formes de nom des personnes et des contributions sources de leurs contributions.
4. **purge** — marque pour la redécision les contributions dont la forme de nom devient ambiguë après régénération, supprime les attributions d'identifiant automatiques qu'aucune contribution source des contributions de leur personne ne contient, et supprime les personnes sans contribution du périmètre.

`open_tx` gère le commit : `managed_transaction` commite en sortie de bloc si succès, rollback sinon.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection

from infrastructure.repositories.person_repository import PgPersonRepository
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.log_format import LAST_BRANCH
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import waiting
from pipeline.task_runner import TaskStep, run_tasks
from pipeline.transformation.persons.contribution_resolution import resolve_contributions
from pipeline.transformation.persons.identifier_arbitration import arbitrate_identifier_conflicts
from pipeline.transformation.persons.metrics import build_metrics
from pipeline.transformation.persons.populate_person_name_forms import populate
from pipeline.transformation.persons.purge import purge


@dataclass(frozen=True)
class PersonsPhase:
    repo_factory: Callable[[Connection], PgPersonRepository]

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute les quatre tâches de la phase personnes et rend ses métriques."""
        by_task = run_tasks(
            "persons",
            {
                "persons.arbitrate_identifiers": TaskStep(self._arbitrate_identifiers),
                "persons.resolve_contributions": TaskStep(
                    self._resolve_contributions,
                    section="Identification des contributions",
                ),
                "persons.populate_person_name_forms": TaskStep(
                    self._populate,
                    section="Rafraîchissement des formes de nom associées aux personnes",
                ),
                "persons.purge": TaskStep(self._purge),
            },
            ctx,
        )
        return build_metrics(
            resolution=by_task["persons.resolve_contributions"].extras,
            arbitration=by_task["persons.arbitrate_identifiers"].extras,
            name_forms=by_task["persons.populate_person_name_forms"].extras,
            purge=by_task["persons.purge"].extras,
        )

    def _arbitrate_identifiers(self, ctx: PhaseContext) -> PhaseMetrics:
        with ctx.open_tx() as conn:
            counts = arbitrate_identifier_conflicts(conn, ctx.logger, repo=self.repo_factory(conn))
        return PhaseMetrics(extras=counts)

    def _resolve_contributions(self, ctx: PhaseContext) -> PhaseMetrics:
        with ctx.open_tx() as conn:
            counts = resolve_contributions(conn, ctx.logger)
        return PhaseMetrics(extras=counts)

    def _populate(self, ctx: PhaseContext) -> PhaseMetrics:
        t0 = time.perf_counter()
        with (
            ctx.open_tx() as conn,
            waiting(f"{LAST_BRANCH}rafraîchissement en cours", ctx.logger) as line,
        ):
            counts = populate(conn)
            line.conclude(f"{LAST_BRANCH}Terminé en {time.perf_counter() - t0:.1f}s")
        return PhaseMetrics(extras=counts._asdict())

    def _purge(self, ctx: PhaseContext) -> PhaseMetrics:
        with ctx.open_tx() as conn:
            counts = purge(conn)
        return PhaseMetrics(extras=dict(counts))


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    return PersonsPhase(repo_factory=PgPersonRepository)
