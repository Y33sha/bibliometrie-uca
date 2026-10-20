"""Phase `normalize` : normalisation du staging vers `source_publications`, `source_authorships` et `addresses`. Tâches `normalize.<source>`.

Les `source_publications` sortent sans `publication_id` : la phase `publications` les assigne. Pour HAL, les ORCID et IdRef sont lus dans le TEI.

La phase enchaîne ses tâches (`pipeline.graph`) :

1. la normalisation de chaque source retenue, dans l'ordre de `SOURCE_PRIORITY` ;
2. la suppression des `source_publications` dont le staging porte `disappeared_at` ;
3. le nettoyage des identités d'auteur orphelines (la normalisation réassigne des signatures et la suppression précédente en retire, laissant des `author_identifying_keys` que plus aucune signature ne référence) ;
4. le nettoyage des adresses orphelines, pour la même raison. Sa maintenance, lancée par l'exécuteur, est le `VACUUM` du staging (`raw_data` vidé après normalisation) : `VACUUM FULL` en mode full, simple sinon.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from sqlalchemy import Connection

from domain.sources.registry import SOURCE_PRIORITY, source_label
from infrastructure.raw_store import NullRawStore, get_raw_store
from pipeline.ingestion.common.normalizer import (
    BibliographicNormalizer,
    NormalizeStats,
    SourceNormalizer,
)
from pipeline.ingestion.common.signature_queries import (
    AuthorshipsBatchQueries,
    delete_orphan_addresses,
    delete_orphan_identities,
    mark_signatures_to_resync,
)
from pipeline.ingestion.common.source_publications import (
    SourcePublicationQueries,
    delete_disappeared_source_publications,
)
from pipeline.ingestion.common.staging import StagingQueries
from pipeline.ingestion.crossref.normalize import CrossrefNormalizer
from pipeline.ingestion.datacite.normalize import DataciteNormalizer
from pipeline.ingestion.hal.normalize import HalNormalizer
from pipeline.ingestion.openalex.normalize import OpenalexNormalizer
from pipeline.ingestion.scanr.normalize import ScanrNormalizer
from pipeline.ingestion.theses.normalize import ThesesNormalizer
from pipeline.ingestion.wos.normalize import WosNormalizer
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.libelles import (
    DERNIERE_BRANCHE,
    accord,
)
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import TaskRun, TaskStep, run_tasks
from pipeline.transformation.publishing.containers import ContainerGatewayQueries
from pipeline.transformation.publishing.publishers.publishers import PublisherGatewayQueries

NormalizeOne = Callable[[PhaseContext, str], NormalizeStats]
"""Normalise une source (connexion + normaliseur câblé) et rend son bilan."""


def _retenue(source: str) -> Callable[[PhaseContext], bool]:
    """Condition d'exécution de la tâche de `source` : la source fait partie des sources du run."""
    return lambda ctx: source in ctx.options.sources


@dataclass(frozen=True)
class NormalizePhase:
    """Le run normalise les sources de ses options, toutes quand il n'en restreint aucune, dans l'ordre de `SOURCE_PRIORITY`."""

    normalize_one: NormalizeOne
    prune_disappeared: Callable[[PhaseContext], int]
    cleanup_orphan_identities: Callable[[PhaseContext], int]
    cleanup_orphan_addresses: Callable[[PhaseContext], int]

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Normalise les sources retenues, retire les documents disparus, nettoie les identités et les adresses orphelines ; l'exécuteur lance ensuite le `VACUUM` du staging."""
        sources = [source.value for source in SOURCE_PRIORITY]
        steps = {
            f"normalize.{source}": TaskStep(
                self._normalize_task(source),
                label=source_label(source),
                progress_bar=True,
                when=_retenue(source),
            )
            for source in sources
        }
        steps["normalize.prune_disappeared"] = TaskStep(self._prune)
        steps["normalize.cleanup_orphan_identities"] = TaskStep(
            self._cleanup, section="Maintenance des tables", label="Identités d'auteur orphelines"
        )
        steps["normalize.cleanup_orphan_addresses"] = TaskStep(
            self._cleanup_addresses, section="Maintenance des tables", label="Adresses orphelines"
        )
        by_task = run_tasks("normalize", steps, ctx)

        rows = [
            {
                **cast("dict[str, object]", task.details["row"]),
                "duration_s": task.duration_s,
            }
            for source in sources
            if "row" in (task := by_task[f"normalize.{source}"]).details
        ]
        metrics = PhaseMetrics()
        normalises = sum(cast("int", row["processed"]) for row in rows)
        metrics.add(seen=normalises)
        metrics.details["table"] = {"rows": rows}
        metrics.details["disappeared_pruned"] = by_task["normalize.prune_disappeared"].extras.get(
            "disappeared", 0
        )
        return metrics

    def _normalize_task(self, source: str) -> TaskRun:
        """Tâche `normalize.<source>` : normalise la source et garde sa ligne de la table d'observabilité."""

        def run(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            stats = self.normalize_one(ctx, source)
            metrics = PhaseMetrics()
            metrics.details["row"] = {
                "key": source,
                "processed": stats.processed,
                "skipped": stats.skipped,
                "errors": stats.errors,
            }
            return metrics

        return run

    def _prune(self, ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
        """Supprime les documents disparus de leur source, et ferme la section de normalisation."""
        disparues = self.prune_disappeared(ctx)
        if disparues:
            ctx.logger.info(
                "%s%s (disparus de leur source)",
                DERNIERE_BRANCHE,
                accord(disparues, "document supprimé", "documents supprimés"),
            )
        else:
            ctx.logger.info("%saucun document disparu de sa source", DERNIERE_BRANCHE)
        return PhaseMetrics(extras={"disappeared": disparues})

    def _cleanup(self, ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
        supprimees = self.cleanup_orphan_identities(ctx)
        metrics = PhaseMetrics()
        if supprimees:
            metrics.report = f"{accord(supprimees, 'identité supprimée', 'identités supprimées')}"
        return metrics

    def _cleanup_addresses(self, ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
        supprimees = self.cleanup_orphan_addresses(ctx)
        metrics = PhaseMetrics()
        if supprimees:
            metrics.report = f"{accord(supprimees, 'adresse supprimée', 'adresses supprimées')}"
        return metrics


# ── Câblage ───────────────────────────────────────────────────


type ConstructeurNormalizer = Callable[[Connection, logging.Logger], SourceNormalizer]


def build() -> Phase:
    return _NormalizeSelonOptions()


class _NormalizeSelonOptions:
    """Construit les normaliseurs selon les options du run (`--raw-store`), puis exécute `NormalizePhase`.

    Avec `--normalize-full`, chaque source marque d'abord toutes ses notices à resynchroniser.
    """

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        options = ctx.options
        registry = _normalize_builders(archive=options.raw_store)

        def normalize_one(ctx: PhaseContext, source: str) -> NormalizeStats:
            if options.normalize_full:
                _run_mark_signatures_to_resync(ctx, source)
            return _run_normalize(ctx, registry[source])

        return NormalizePhase(
            normalize_one=normalize_one,
            prune_disappeared=_run_prune_disappeared,
            cleanup_orphan_identities=_run_cleanup_orphan_identities,
            cleanup_orphan_addresses=_run_cleanup_orphan_addresses,
        ).run(ctx)


def _run_mark_signatures_to_resync(ctx: PhaseContext, source: str) -> None:
    with ctx.open_tx() as conn:
        mark_signatures_to_resync(conn, source)


def _run_prune_disappeared(ctx: PhaseContext) -> int:
    with ctx.open_tx() as conn:
        return delete_disappeared_source_publications(conn)


def _run_cleanup_orphan_identities(ctx: PhaseContext) -> int:
    with ctx.open_tx() as conn:
        return delete_orphan_identities(conn)


def _run_cleanup_orphan_addresses(ctx: PhaseContext) -> int:
    with ctx.open_tx() as conn:
        return delete_orphan_addresses(conn)


def _normalize_builders(*, archive: bool = True) -> dict[str, ConstructeurNormalizer]:
    """Constructeur du normaliseur de chaque source. Les sources bibliographiques partagent le câblage `_biblio` ; `theses` a le sien, sans repository de revue ni d'éditeur."""

    raw_store = get_raw_store() if archive else NullRawStore()

    def _biblio(cls: type[BibliographicNormalizer]) -> ConstructeurNormalizer:
        return lambda conn, logger: cls(
            conn,
            logger,
            StagingQueries(raw_store),
            SourcePublicationQueries(),
            container_repo=ContainerGatewayQueries(conn),
            publisher_repo=PublisherGatewayQueries(conn),
            authorship_queries=AuthorshipsBatchQueries(),
        )

    return {
        "theses": lambda conn, logger: ThesesNormalizer(
            conn,
            logger,
            StagingQueries(raw_store),
            SourcePublicationQueries(),
            batch_queries=AuthorshipsBatchQueries(),
        ),
        "crossref": _biblio(CrossrefNormalizer),
        "datacite": _biblio(DataciteNormalizer),
        "scanr": _biblio(ScanrNormalizer),
        "hal": _biblio(HalNormalizer),
        "openalex": _biblio(OpenalexNormalizer),
        "wos": _biblio(WosNormalizer),
    }


def _run_normalize(ctx: PhaseContext, build: ConstructeurNormalizer) -> NormalizeStats:
    with ctx.open_tx() as conn:
        return build(conn, ctx.logger).run()
