"""Orchestrateur de la phase `metadata_correction` : persistance des corrections de métadonnées sur les `source_records`.

Quatre tâches (`pipeline.graph`), chacune dans sa propre transaction, dans l'ordre du graphe :

1. **serial_by_doi** — rattache la revue manquante que désigne l'espace de noms du DOI. En premier : le `serial_id` qu'il commit est consommé par l'étape suivante (`serial_type` depuis la colonne vivante), de sorte que la reclassification `doc_type` journal-dépendante a lieu dans le même run, sans feed-forward.
2. **unaire** (per-record) — règles de correction `effective_metadata`, retrait des dépôts HAL introuvables.
3. **cluster** (group-by-DOI) — substitution version→concept DataCite, nullage des DOI erronés ouvrage/chapitre et des DOI inconnus de doi.org.
4. **matchable** — enregistrements sources écartés de la réconciliation (`is_matchable`), d'après les valeurs corrigées.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import TaskStep, run_tasks
from pipeline.transformation.publications.correction.correct_by_cluster import run as run_cluster
from pipeline.transformation.publications.correction.correct_unary import run as run_unary
from pipeline.transformation.publications.correction.correction_store import (
    SourceRecordCorrectionStore,
)
from pipeline.transformation.publications.correction.matchable import run as run_matchable
from pipeline.transformation.publications.correction.serial_by_doi import run as run_serial_by_doi

_PHASE = "metadata_correction"


@dataclass(frozen=True)
class MetadataCorrectionPhase:
    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute les quatre tâches, chacune dans sa transaction, et assemble les métriques de la phase."""
        by_task = run_tasks(_PHASE, self._steps(), ctx)
        serial_by_doi, unary, cluster, matchable = (
            by_task[f"{_PHASE}.{name}"]
            for name in ("serial_by_doi", "unary", "cluster", "matchable")
        )

        metrics = PhaseMetrics()
        for node_metrics in (serial_by_doi, unary, cluster, matchable):
            metrics.add(seen=node_metrics.total, updated=node_metrics.updated)
        # Chiffres plats : `{mode}_{examined,corrected}`. Le frontend les arrange en matrice (mode × examinées/corrigées) — pur agencement de présentation.
        metrics.details["summary"] = {
            "serial_by_doi_examined": serial_by_doi.total,
            "serial_by_doi_corrected": serial_by_doi.updated,
            "unary_examined": unary.total,
            "unary_corrected": unary.updated,
            "cluster_examined": cluster.total,
            "cluster_corrected": cluster.updated,
            "matchable_examined": matchable.total,
            "matchable_corrected": matchable.updated,
        }
        counts = list(unary.extras.items()) + list(cluster.extras.items())
        counts.sort(key=lambda kc: kc[1], reverse=True)
        metrics.details["table"] = {"rows": [{"key": key, "count": count} for key, count in counts]}
        return metrics

    def _steps(self) -> dict[str, TaskStep]:
        """Étape de chaque tâche. Chacune écrit sa section du journal et rend examinés (`total`), corrigés (`updated`) et décompte par règle (`extras`)."""

        def serial_by_doi(ctx: PhaseContext) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                stats = run_serial_by_doi(conn, SourceRecordCorrectionStore(conn), ctx.logger)
            return PhaseMetrics(seen=stats.examined, updated=stats.attached)

        def unary(ctx: PhaseContext) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                stats = run_unary(conn, SourceRecordCorrectionStore(conn), ctx.logger)
            return PhaseMetrics(
                seen=stats.examined, updated=stats.corrected, extras=dict(stats.rule_counts)
            )

        def cluster(ctx: PhaseContext) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                stats = run_cluster(conn, SourceRecordCorrectionStore(conn), ctx.logger)
            return PhaseMetrics(
                seen=stats.examined, updated=stats.corrected, extras=dict(stats.case_counts)
            )

        def matchable(ctx: PhaseContext) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                stats = run_matchable(conn, SourceRecordCorrectionStore(conn), ctx.logger)
            return PhaseMetrics(seen=stats.examined, updated=stats.changed)

        return {
            f"{_PHASE}.serial_by_doi": TaskStep(serial_by_doi),
            f"{_PHASE}.unary": TaskStep(unary),
            f"{_PHASE}.cluster": TaskStep(cluster),
            f"{_PHASE}.matchable": TaskStep(matchable),
        }


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    return MetadataCorrectionPhase()
