"""Phase `metadata_correction` : écriture sur les enregistrements sources de leurs métadonnées corrigées.

Cinq tâches (`pipeline.graph`), chacune dans sa transaction, dans l'ordre du graphe :

1. **serial_by_doi** rattache la revue manquante que désigne l'espace de noms du DOI. Elle passe en premier : la correction unaire lit le type de la revue rattachée, et requalifie le document au même run.
2. **unary** applique à chaque enregistrement source les règles de correction (`correct_source_record`), et retire les dépôts HAL introuvables.
3. **doi_targets** donne une cible au DOI des formes secondaires DataCite d'une œuvre présente en base.
4. **remove_identifiers** retire le DOI que partagent des œuvres distinctes (ouvrage et chapitre, volume d'actes et communication, dépôt HAL d'une autre œuvre), et le DOI inconnu de doi.org.
5. **matchable** écarte de la réconciliation des enregistrements sources (`is_matchable`), d'après les valeurs corrigées.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import TaskStep, run_tasks
from pipeline.transformation.publications.correction.correct_unary import run as run_unary
from pipeline.transformation.publications.correction.correction_store import (
    SourceRecordCorrectionStore,
)
from pipeline.transformation.publications.correction.doi_targets import run as run_doi_targets
from pipeline.transformation.publications.correction.matchable import run as run_matchable
from pipeline.transformation.publications.correction.remove_identifiers import (
    run as run_remove_identifiers,
)
from pipeline.transformation.publications.correction.serial_by_doi import run as run_serial_by_doi

_PHASE = "metadata_correction"
# Tâches de la phase, dans l'ordre du graphe.
_NODES = ("serial_by_doi", "unary", "doi_targets", "remove_identifiers", "matchable")


@dataclass(frozen=True)
class MetadataCorrectionPhase:
    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute les cinq tâches, chacune dans sa transaction, et assemble les métriques de la phase."""
        by_task = run_tasks(_PHASE, self._steps(), ctx)
        nodes = {name: by_task[f"{_PHASE}.{name}"] for name in _NODES}

        metrics = PhaseMetrics()
        for node_metrics in nodes.values():
            metrics.add(seen=node_metrics.total, updated=node_metrics.updated)
        # Chiffres à plat, `{tâche}_{examined,corrected}`, que l'interface dispose en matrice.
        metrics.details["summary"] = {
            f"{name}_{column}": value
            for name, node_metrics in nodes.items()
            for column, value in (
                ("examined", node_metrics.total),
                ("corrected", node_metrics.updated),
            )
        }
        counts = [
            item
            for name in ("unary", "doi_targets", "remove_identifiers")
            for item in nodes[name].extras.items()
        ]
        counts.sort(key=lambda kc: kc[1], reverse=True)
        metrics.details["table"] = {"rows": [{"key": key, "count": count} for key, count in counts]}
        return metrics

    def _steps(self) -> dict[str, TaskStep]:
        """Étape de chaque tâche. Chacune écrit sa section du journal et renvoie examinés (`total`), corrigés (`updated`) et décompte par règle (`extras`)."""

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

        def doi_targets(ctx: PhaseContext) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                stats = run_doi_targets(conn, SourceRecordCorrectionStore(conn), ctx.logger)
            return PhaseMetrics(
                seen=stats.examined, updated=stats.changed, extras=dict(stats.rule_counts)
            )

        def remove_identifiers(ctx: PhaseContext) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                stats = run_remove_identifiers(conn, SourceRecordCorrectionStore(conn), ctx.logger)
            return PhaseMetrics(
                seen=stats.examined, updated=stats.corrected, extras=dict(stats.case_counts)
            )

        def matchable(ctx: PhaseContext) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                stats = run_matchable(conn, SourceRecordCorrectionStore(conn), ctx.logger)
            return PhaseMetrics(seen=stats.examined, updated=stats.changed)

        steps = {
            "serial_by_doi": serial_by_doi,
            "unary": unary,
            "doi_targets": doi_targets,
            "remove_identifiers": remove_identifiers,
            "matchable": matchable,
        }
        return {f"{_PHASE}.{name}": TaskStep(steps[name]) for name in _NODES}


def build() -> Phase:
    return MetadataCorrectionPhase()
