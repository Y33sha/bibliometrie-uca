"""Phase `subjects` : sujets des publications (`subject_ingestion`), puis usage des sujets et cooccurrences (`subject_cooccurrences`). Chaque tâche a sa transaction. La phase est idempotente.

La phase `finalize` supprime au préalable les publications sans contribution rattachée à une personne. `publication_subjects` et ses compteurs dérivés couvrent donc le périmètre.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import TaskStep, run_tasks
from pipeline.transformation.publications.subjects.subject_cooccurrences import (
    run as run_cooccurrences,
)
from pipeline.transformation.publications.subjects.subject_ingestion import run as run_ingest
from pipeline.transformation.publications.subjects.subject_store import SubjectStore


@dataclass(frozen=True)
class SubjectsPhase:
    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Ingère les sujets, puis recalcule l'usage des sujets et les cooccurrences. Renvoie les métriques d'ingestion. L'option `rebuild_subjects` force la ré-ingestion de toutes les publications."""

        def ingest(ctx: PhaseContext) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                return run_ingest(
                    SubjectStore(conn), ctx.logger, rebuild=ctx.options.rebuild_subjects
                )

        def usage(ctx: PhaseContext) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                run_cooccurrences(SubjectStore(conn), ctx.logger)
            return PhaseMetrics()

        by_task = run_tasks(
            "subjects",
            {"subjects.ingest": TaskStep(ingest), "subjects.usage": TaskStep(usage)},
            ctx,
        )
        return by_task["subjects.ingest"]


def build() -> Phase:
    return SubjectsPhase()
