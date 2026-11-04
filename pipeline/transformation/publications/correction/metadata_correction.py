"""Phase `metadata_correction` : écriture sur les enregistrements sources de leurs métadonnées corrigées.

Tâches (`pipeline.graph`), chacune dans sa transaction, dans l'ordre du graphe :

- **serial_by_doi** rattache la revue manquante désignée par l'espace de noms du DOI. Elle passe en premier : la correction unaire lit le type de la revue rattachée, et requalifie l'enregistrement source au même run.
- **unary** applique à chaque enregistrement source les règles de correction (`correct_source_record`), et retire les dépôts HAL introuvables.
- **doi_targets** donne une cible au DOI des formes secondaires DataCite d'une œuvre présente en base.
- **remove_identifiers** retire le DOI partagé par des œuvres distinctes (ouvrage et chapitre, volume d'actes et communication, enregistrement source d'une autre œuvre), et le DOI inconnu de doi.org.
- **matchable** écarte de la réconciliation des enregistrements sources (`is_matchable`), d'après les valeurs corrigées.
"""

from __future__ import annotations

from collections.abc import Mapping

from pipeline.graph import Task
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
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


# Chaque tâche écrit sa section du journal et renvoie examinés (`total`), corrigés (`updated`) et décompte par règle (`extras`).
def _serial_by_doi(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        stats = run_serial_by_doi(conn, SourceRecordCorrectionStore(conn), ctx.logger)
    return PhaseMetrics(seen=stats.examined, updated=stats.attached)


def _unary(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        stats = run_unary(conn, SourceRecordCorrectionStore(conn), ctx.logger)
    return PhaseMetrics(
        seen=stats.examined, updated=stats.corrected, extras=dict(stats.rule_counts)
    )


def _doi_targets(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        stats = run_doi_targets(conn, SourceRecordCorrectionStore(conn), ctx.logger)
    return PhaseMetrics(seen=stats.examined, updated=stats.changed, extras=dict(stats.rule_counts))


def _remove_identifiers(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        stats = run_remove_identifiers(conn, SourceRecordCorrectionStore(conn), ctx.logger)
    return PhaseMetrics(
        seen=stats.examined, updated=stats.corrected, extras=dict(stats.case_counts)
    )


def _matchable(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        stats = run_matchable(conn, SourceRecordCorrectionStore(conn), ctx.logger)
    return PhaseMetrics(seen=stats.examined, updated=stats.changed)


TASKS = (
    Task(
        "serial_by_doi",
        reads=(
            "serial_doi_namespaces",
            "source_record_identifiers",
            "source_records.serial_id",
            "source_records.corrections",
            "source_records.doc_type",
        ),
        writes=(
            "source_records.serial_id",
            "source_records.corrections",
            "source_record_keys_queue",
        ),
        # Espaces de noms des revues vides, supprimés avec elles par `finalize.delete_empty_serials`.
        previous_run=(
            "source_records",
            "source_record_identifiers.removed_by",
            "serial_doi_namespaces",
        ),
        run=_serial_by_doi,
    ),
    Task(
        "unary",
        reads=(
            *(
                f"source_records.{column}"
                for column in (
                    "id",
                    "source",
                    "source_id",
                    "title",
                    "doc_type",
                    "serial_id",
                    "monograph_id",
                    "language",
                    "urls",
                    "corrections",
                    "source_extras",
                )
            ),
            "serials.serial_type",
            "monographs.proceedings",
            "doi_prefixes.publisher_id",
            "publishers.publisher_type",
            "language_forms",
            "source_contributions.source_record_id",
            "source_record_identifiers",
            # Dépôts HAL introuvables dans HAL.
            "failed_lookups",
        ),
        writes=(
            "source_records.doc_type",
            "source_records.language",
            "source_records.urls",
            "source_records.corrections",
            "source_record_identifiers.removed_by",
            "source_record_locations",
            "source_record_keys_queue",
        ),
        # Les référentiels vides, supprimés plus loin, ne sont référencés par aucun enregistrement source : la correction ne les atteint pas.
        previous_run=(
            "source_records",
            "source_record_identifiers.removed_by",
            "serials.serial_type",
            "serials.oa_model",
            "serials.is_in_doaj",
            "serials.doaj_payload",
            "monographs.proceedings",
            "publishers.publisher_type",
        ),
        run=_unary,
    ),
    Task(
        "doi_targets",
        reads=tuple(
            f"source_records.{column}"
            for column in (
                "id",
                "source",
                "doc_type",
                "title_normalized",
                "publication_year",
                "corrections",
                "source_extras",
            )
        )
        # DOI présents en base.
        + ("source_record_identifiers",)
        # DOI inconnus de doi.org.
        + ("failed_lookups",),
        writes=("doi_targets", "source_record_keys_queue"),
        previous_run=("source_records", "source_record_identifiers.removed_by", "doi_targets"),
        run=_doi_targets,
    ),
    Task(
        "remove_identifiers",
        reads=tuple(
            f"source_records.{column}"
            for column in (
                "id",
                "source",
                "doc_type",
                "title_normalized",
                "corrections",
                "source_id",
            )
        )
        + ("source_record_identifiers", "doi_targets")
        # DOI inconnus de doi.org.
        + ("failed_lookups",)
        # Noms des auteurs d'un dépôt HAL et de l'enregistrement source Crossref de son DOI.
        + (
            "source_contributions.source_record_id",
            "source_contributions.contributor_information_id",
            "source_contributions.collective",
            "contributor_information",
        ),
        writes=(
            "source_record_identifiers.removed_by",
            "source_record_keys_queue",
        ),
        previous_run=("source_records", "source_record_identifiers.removed_by"),
        run=_remove_identifiers,
    ),
    Task(
        "matchable",
        reads=(
            *(
                f"source_records.{column}"
                for column in (
                    "id",
                    "source",
                    "source_id",
                    "title_normalized",
                    "urls",
                    "corrections",
                    "is_matchable",
                )
            ),
            "source_record_identifiers",
            "doi_targets",
            # Dépôts HAL introuvables dans HAL.
            "failed_lookups",
        ),
        writes=("source_records.is_matchable", "source_record_keys_queue"),
        previous_run=("source_records.is_matchable",),
        run=_matchable,
    ),
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie les métriques de la phase : compteurs des tâches, chiffres par tâche, et décompte par règle."""
    metrics = PhaseMetrics()
    for task_metrics in by_task.values():
        metrics.add(seen=task_metrics.total, updated=task_metrics.updated)
    # Chiffres à plat, `{tâche}_{examined,corrected}`, disposés en matrice par l'interface.
    metrics.details["summary"] = {
        f"{name}_{column}": value
        for name, task_metrics in by_task.items()
        for column, value in (
            ("examined", task_metrics.total),
            ("corrected", task_metrics.updated),
        )
    }
    counts = [
        item
        for name in ("unary", "doi_targets", "remove_identifiers")
        for item in by_task[name].extras.items()
    ]
    counts.sort(key=lambda kc: kc[1], reverse=True)
    metrics.details["table"] = {"rows": [{"key": key, "count": count} for key, count in counts]}
    return metrics
