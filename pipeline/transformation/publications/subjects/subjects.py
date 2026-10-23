"""Orchestrateur de la phase `subjects` : sujets / mots-clés et co-occurrences.

Deux tâches (`pipeline.graph`), chacune dans sa propre transaction :

1. **ingestion** (`subjects` + `publication_subjects`) — incrémentale et publication-centrée : ingère seulement les publications jamais ingérées, ou recalculées depuis leurs sources après leur dernière ingestion, à partir des `topics` de leurs `source_records`. Purge en fin les sujets devenus orphelins.
2. **co-occurrences** (`subjects.usage_count` + matview `subject_cooccurrences`) — recalcule l'usage de chaque sujet et rafraîchit la matview des paires de sujets co-présents sur une même publication.

Aucun filtre périmètre : la phase `contributions` a purgé en amont les publications orphelines, donc `publication_subjects` ne porte que du périmètre et les deux caches en héritent. Idempotente.

`--rebuild-subjects` reprend toutes les publications, pour propager une évolution des règles d'ingestion sur tout le stock.
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
        """Ingestion des sujets puis recalcul des co-occurrences ; retourne les métriques d'ingestion. L'option `rebuild_subjects` force la ré-ingestion de toutes les publications."""

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


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    return SubjectsPhase()
