"""Phase `subjects` : sujets des publications (`subject_ingestion`). La phase est idempotente.

La tâche `count_subject_usage` recalcule l'usage des sujets et leurs cooccurrences (`subject_cooccurrences`). La phase `finalize` l'exécute après la purge des publications, donc ses décomptes couvrent le périmètre.
"""

from __future__ import annotations

from pipeline.graph import Block, Phase, Task, in_transaction
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publications.subjects.subject_cooccurrences import (
    run as run_cooccurrences,
)
from pipeline.transformation.publications.subjects.subject_ingestion import run as run_ingest


def _ingest(ctx: PhaseContext) -> PhaseMetrics:
    """Ingère les sujets. L'option `rebuild_subjects` force la ré-ingestion de toutes les publications."""
    with ctx.open_tx() as conn:
        return run_ingest(conn, ctx.logger, rebuild=ctx.options.rebuild_subjects)


_DERIVE_PUBLICATION_SUBJECTS = Task(
    "derive_publication_subjects",
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
    previous_runs=(
        "publications.subjects_ingested_at",
        "subjects",
        # Publications et liens supprimés, enregistrements sources détachés par `finalize.purge_publications`.
        "publications.id",
        "publication_subjects",
        "source_records.publication_id",
    ),
    run=_ingest,
    section="Liens publications-sujets",
)

COUNT_SUBJECT_USAGE = Task(
    "count_subject_usage",
    reads=(
        "publication_subjects",
        "subjects.id",
        "subjects.label",
        "subjects.label_normalized",
    ),
    writes=("subjects.usage_count", "subject_labels", "subject_cooccurrences"),
    previous_runs=("subjects",),
    run=in_transaction(run_cooccurrences),
    section="Rafraîchissement des décomptes de sujets",
)
"""Usage des sujets et cooccurrences, exécutés par la phase `finalize`."""


PHASE = Phase(
    "subjects",
    "Sujets des publications",
    (_DERIVE_PUBLICATION_SUBJECTS,),
    Block.ENTITIES,
)
