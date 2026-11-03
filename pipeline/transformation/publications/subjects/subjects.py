"""Phase `subjects` : sujets des publications (`subject_ingestion`), puis usage des sujets et cooccurrences (`subject_cooccurrences`). Chaque tâche a sa transaction. La phase est idempotente.

La phase `finalize` supprime au préalable les publications sans contribution rattachée à une personne. `publication_subjects` et ses compteurs dérivés couvrent donc le périmètre.
"""

from __future__ import annotations

from pipeline.graph import Task
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publications.subjects.subject_cooccurrences import (
    run as run_cooccurrences,
)
from pipeline.transformation.publications.subjects.subject_ingestion import run as run_ingest
from pipeline.transformation.publications.subjects.subject_store import SubjectStore


def _ingest(ctx: PhaseContext) -> PhaseMetrics:
    """Ingère les sujets. L'option `rebuild_subjects` force la ré-ingestion de toutes les publications."""
    with ctx.open_tx() as conn:
        return run_ingest(SubjectStore(conn), ctx.logger, rebuild=ctx.options.rebuild_subjects)


def _usage(ctx: PhaseContext) -> PhaseMetrics:
    """Recalcule l'usage des sujets et les cooccurrences."""
    with ctx.open_tx() as conn:
        run_cooccurrences(SubjectStore(conn), ctx.logger)
    return PhaseMetrics()


TASKS = (
    Task(
        "ingest",
        reads=(
            "publications.id",
            "publications.subjects_ingested_at",
            "source_records.publication_id",
            "source_records.source",
            "source_record_subjects",
            "subjects",
            "publication_subjects",
        ),
        writes=("publication_subjects", "subjects.id", "publications.subjects_ingested_at"),
        previous_run=("publications.subjects_ingested_at", "subjects"),
        run=_ingest,
    ),
    Task(
        "usage",
        reads=(
            "publication_subjects",
            "subjects.id",
            "subjects.label",
            "subjects.label_normalized",
        ),
        writes=("subjects.usage_count", "subject_labels", "subject_cooccurrences"),
        previous_run=("subjects",),
        run=_usage,
    ),
)
