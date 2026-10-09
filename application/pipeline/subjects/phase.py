"""Orchestrateur de la phase `subjects` : sujets / mots-clés et co-occurrences.

Deux sous-étapes enchaînées, indissociables, chacune dans sa propre transaction :

1. **ingestion** (`subjects` + `publication_subjects`) — incrémentale et publication-centrée : ingère seulement les publications jamais ingérées, ou recalculées depuis leurs sources après leur dernière ingestion, à partir des `topics` de leurs `source_publications`. Purge en fin les sujets devenus orphelins.
2. **co-occurrences** (`subjects.usage_count` + matview `subject_cooccurrences`) — recalcule l'usage de chaque sujet et rafraîchit la matview des paires de sujets co-présents sur une même publication.

Aucun filtre périmètre : la phase `authorships` a purgé en amont les publications orphelines, donc `publication_subjects` ne porte que du périmètre et les deux caches en héritent. Idempotente.
"""

from dataclasses import dataclass

from application.pipeline.context import PhaseContext
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.subjects.cooccurrences import run as run_cooccurrences
from application.pipeline.subjects.ingestion import run as run_ingest
from application.ports.pipeline.subjects import SubjectsIngestionQueries


@dataclass(frozen=True)
class SubjectsPhase:
    queries: SubjectsIngestionQueries

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Ingestion des sujets puis recalcul des co-occurrences ; retourne les métriques d'ingestion. L'option `rebuild_subjects` force la ré-ingestion de toutes les publications."""
        open_tx, queries, logger = ctx.open_tx, self.queries, ctx.logger
        with open_tx() as conn:
            metrics = run_ingest(conn, queries, logger, rebuild=ctx.options.rebuild_subjects)

        with open_tx() as conn:
            run_cooccurrences(conn, queries, logger)
        # Chaque sous-étape journalise son résultat : une ligne de clôture le répéterait.
        metrics.resume = ""
        return metrics
