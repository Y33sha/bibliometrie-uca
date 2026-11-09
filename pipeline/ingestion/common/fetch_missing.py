"""Phase `fetch_missing` : rattrapage des documents repérés dans une source mais absents d'une autre.

1. **Recherche par hal-id** : dans HAL, les hal-id repérés dans OpenAlex et ScanR (`pipeline.ingestion.hal.fetch_missing`) ; dans ScanR, les hal-id repérés dans HAL et OpenAlex (`pipeline.ingestion.scanr.fetch_missing`). Les deux tâches forment un groupe parallèle.
2. **Recherche par NNT** : dans HAL, en mode `full`, les thèses de theses.fr sans document HAL (`pipeline.ingestion.hal.fetch_missing`) ; dans theses.fr, les NNT repérés dans une autre source (`pipeline.ingestion.theses.fetch_missing`). Les deux tâches forment un groupe parallèle.
3. **Recherche par numéro de brevet** : dans ScanR brevets, les familles des numéros repérés dans une autre source (`pipeline.ingestion.scanr_patents.fetch_missing`).
4. **Recherche par DOI** : pour chaque source cible, les DOI vus ailleurs et absents de la cible. Les tâches `doi.<source>` forment un groupe parallèle.

Une section sans identifiant à chercher se ferme sur « Rien à faire ».

Un identifiant cherché en vain est inscrit dans `failed_lookups`, et cherché de nouveau après le délai `fetch_missing_retry_after_days`. Auprès du registre qui l'attribue (HAL pour un hal-id, theses.fr pour un NNT, doi.org pour un DOI), l'échec est définitif. WoS est opt-in (`--include-wos`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Mapping

from domain.config import ConfigKey
from domain.sources.registry import DOI_SEARCHABLE_SOURCES, PROFILES, Source, source_label
from pipeline.graph import Step, Task, TaskRun
from pipeline.ingestion.adapters import adapter
from pipeline.ingestion.common.doi_search import fetch_missing_doi
from pipeline.ingestion.hal.fetch_missing import fetch_missing_hal_by_id, fetch_missing_hal_by_nnt
from pipeline.ingestion.scanr.fetch_missing import fetch_missing_scanr_by_hal_id
from pipeline.ingestion.scanr_patents.fetch_missing import fetch_missing_scanr_patents_by_number
from pipeline.ingestion.theses.fetch_missing import fetch_missing_theses_by_nnt
from pipeline.runtime.config import cap, delay, window_years
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import assemble_by_source

_HAL_BY_ID = "hal_by_id"
_SCANR_BY_HAL_ID = "scanr_by_hal_id"
_HAL_BY_NNT = "hal_by_nnt"
_THESES_BY_NNT = "theses_by_nnt"
_SCANR_PATENTS_BY_NUMBER = "scanr_patents_by_number"


def _doi_task(target: str) -> str:
    return f"doi.{target}"


def _summary(metrics: PhaseMetrics) -> dict[str, float | None]:
    """Renvoie la ligne « par canal » de la table d'observabilité de la phase."""
    return {
        "interrogated": metrics.total,
        "new": metrics.new,
        "not_found": metrics.extras.get("not_found", 0),
        "duration_s": metrics.duration_s,
    }


def _by_identifier(search: Callable[..., Coroutine[object, object, PhaseMetrics]]) -> TaskRun:
    """Renvoie l'exécution d'une recherche par hal-id ou par NNT, avec le délai avant de chercher de nouveau un identifiant introuvable."""

    def run(ctx: PhaseContext) -> PhaseMetrics:
        with ctx.open_tx() as conn:
            retry_after_days = delay(conn, ConfigKey.FETCH_MISSING_RETRY_AFTER_DAYS)
            return asyncio.run(search(conn, ctx.logger, retry_after_days=retry_after_days))

    return run


def _run_fetch_missing_doi(ctx: PhaseContext, target: str) -> PhaseMetrics:
    search = adapter(Source(target)).doi_search
    assert search is not None, f"{target} : source interrogeable par DOI sans recherche"
    options = ctx.options
    with ctx.open_tx() as conn:
        retry_after_days = delay(conn, ConfigKey.FETCH_MISSING_RETRY_AFTER_DAYS)
        limit = cap(conn, ConfigKey.FETCH_MISSING_MAX_PER_SOURCE)
        years = window_years(conn, options.years)
        return asyncio.run(
            fetch_missing_doi(
                conn,
                target,
                search,
                ctx.logger,
                retry_after_days=retry_after_days,
                limit=limit,
                years=years,
            )
        )


def _channel(
    name: str,
    *,
    reads: tuple[str, ...] = (),
    previous_run: tuple[str, ...] = (),
    network: str,
    parallel_group: str,
    run: TaskRun,
    when: Callable[[PhaseContext], bool] | None = None,
) -> Task:
    """Renvoie la tâche d'un canal de recherche, exécutée quand le run interroge sa source et que `when` est remplie.

    Les canaux partagent leurs lectures et leurs écritures : identifiants des publications du périmètre, cherchés dans les autres sources ; échecs retenus dans `failed_lookups`.
    """
    return Task(
        name,
        reads=(
            "config",
            "staging",
            "failed_lookups",
            "source_records.source",
            "source_record_identifiers",
            "source_records.publication_id",
            "publications.in_perimeter",
            *reads,
        ),
        writes=("staging", "staging_normalization_queue", "failed_lookups"),
        previous_run=(
            "staging",
            "failed_lookups",
            "source_records",
            "source_record_identifiers",
            "publications.in_perimeter",
            *previous_run,
        ),
        network=network,
        parallel_group=parallel_group,
        run=run,
        label=source_label(network),
        progress_bar=True,
        when=lambda ctx: network in ctx.options.queried_sources and (when is None or when(ctx)),
        silent_when_empty=True,
    )


STEPS = (
    Step(
        "by_hal_id",
        "hal-id trouvés dans une autre source → documents absents de HAL ou de ScanR",
        (
            _channel(
                _HAL_BY_ID,
                network="hal",
                parallel_group="hal_id",
                run=_by_identifier(fetch_missing_hal_by_id),
            ),
            _channel(
                _SCANR_BY_HAL_ID,
                reads=("source_records.source_id",),
                network="scanr",
                parallel_group="hal_id",
                run=_by_identifier(fetch_missing_scanr_by_hal_id),
            ),
        ),
        label="Recherche des documents avec hal-id trouvés ailleurs",
    ),
    Step(
        "by_nnt",
        "NNT trouvés dans une autre source → thèses absentes de HAL ou de theses.fr",
        (
            _channel(
                _HAL_BY_NNT,
                reads=("publications.doc_type",),
                previous_run=("publications.doc_type",),
                network="hal",
                parallel_group="nnt",
                run=_by_identifier(fetch_missing_hal_by_nnt),
                when=lambda ctx: ctx.options.policy.hal_theses_by_nnt,
            ),
            _channel(
                _THESES_BY_NNT,
                network="theses",
                parallel_group="nnt",
                run=_by_identifier(fetch_missing_theses_by_nnt),
            ),
        ),
        label="Recherche par NNT des thèses trouvées ailleurs",
    ),
    Step(
        "by_patent_number",
        "numéros de brevet trouvés dans une autre source → familles de brevets absentes de ScanR brevets",
        (
            _channel(
                _SCANR_PATENTS_BY_NUMBER,
                network="scanr_patents",
                parallel_group="patent_number",
                run=_by_identifier(fetch_missing_scanr_patents_by_number),
            ),
        ),
        label="Recherche par numéro des brevets trouvés ailleurs",
    ),
    Step(
        "by_doi",
        "DOI trouvés dans une autre source → documents absents de chaque source",
        tuple(
            _channel(
                _doi_task(target),
                # DOI candidats de la vue `candidate_dois`, bornés à la fenêtre d'années du run par les enregistrements sources de leur publication, et agence d'enregistrement pour Crossref et DataCite.
                reads=(
                    "source_record_identifiers",
                    "source_records.publication_year",
                    "publication_relations",
                    *(("doi_prefixes.ra",) if PROFILES[target].registration_agency else ()),
                ),
                previous_run=("doi_prefixes", "publication_relations"),
                network=target,
                parallel_group="doi",
                run=lambda ctx, target=target: _run_fetch_missing_doi(ctx, target),
            )
            for target in DOI_SEARCHABLE_SOURCES
        ),
        label="Recherche par DOI des documents manquants dans chaque source",
    ),
)

_CHANNEL_KEYS = {
    _HAL_BY_ID: "hal-id",
    _SCANR_BY_HAL_ID: "hal-id ScanR",
    _HAL_BY_NNT: "NNT",
    _THESES_BY_NNT: "NNT theses.fr",
    _SCANR_PATENTS_BY_NUMBER: "numéro de brevet ScanR",
    **{_doi_task(target): target for target in DOI_SEARCHABLE_SOURCES},
}
"""Clé de chaque canal dans la table d'observabilité de la phase."""


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie la somme des métriques des canaux, avec la table des canaux interrogés."""
    return assemble_by_source(by_task, _summary, key=_CHANNEL_KEYS.__getitem__)
