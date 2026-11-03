"""Phase `fetch_missing` : rattrapage des documents repérés dans une source mais absents d'une autre.

1. **Recherche par hal-id** : dans HAL, les hal-id repérés dans OpenAlex et ScanR (`pipeline.ingestion.hal.fetch_missing`) ; dans ScanR, les hal-id repérés dans HAL et OpenAlex (`pipeline.ingestion.scanr.fetch_missing`). Les deux tâches forment un groupe parallèle.
2. **Recherche par NNT** : dans HAL, en mode `full`, les thèses de theses.fr sans document HAL (`pipeline.ingestion.hal.fetch_missing`) ; dans theses.fr, les NNT repérés dans une autre source (`pipeline.ingestion.theses.fetch_missing`). Les deux tâches forment un groupe parallèle.
3. **Recherche par DOI** : pour chaque source cible, les DOI vus ailleurs et absents de la cible. Les tâches `fetch_missing.doi.<source>` forment un groupe parallèle.

Une section sans identifiant à chercher se ferme sur « Rien à faire ».

Un identifiant cherché en vain est inscrit dans `failed_lookups`, et cherché de nouveau après le délai `fetch_missing_retry_after_days`. Auprès du registre qui l'attribue (HAL pour un hal-id, theses.fr pour un NNT, doi.org pour un DOI), l'échec est définitif. WoS est opt-in (`--include-wos`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping

from domain.config import ConfigKey
from domain.sources.registry import DOI_SEARCHABLE_SOURCES, PROFILES, Source
from pipeline.graph import Task, TaskRun
from pipeline.ingestion.adapters import ADAPTERS
from pipeline.ingestion.common.doi_search import fetch_missing_doi
from pipeline.runtime.config import cap, delay, window_years
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import select_targets, skipped

_HAL_BY_ID = "fetch_missing.hal_by_id"
_SCANR_BY_HAL_ID = "fetch_missing.scanr_by_hal_id"
_HAL_BY_NNT = "fetch_missing.hal_by_nnt"
_THESES_BY_NNT = "fetch_missing.theses_by_nnt"
_HAL_ID_SECTION = "Recherche des documents avec hal-id trouvés ailleurs"
_NNT_SECTION = "Recherche par NNT des thèses trouvées ailleurs"


def _doi_task(target: str) -> str:
    return f"fetch_missing.doi.{target}"


def _summary(metrics: PhaseMetrics) -> dict[str, float | None]:
    """Renvoie la ligne « par canal » de la table d'observabilité de la phase."""
    return {
        "interrogated": metrics.total,
        "new": metrics.new,
        "not_found": metrics.extras.get("not_found", 0),
        "duration_s": metrics.duration_s,
    }


def _run_fetch_missing_hal_by_id(ctx: PhaseContext) -> PhaseMetrics:
    """Cherche dans HAL, par hal-id, les documents repérés dans OpenAlex ou ScanR et absents du staging."""
    from pipeline.ingestion.hal.fetch_missing import fetch_missing_hal_by_id

    with ctx.open_tx() as conn:
        retry_after_days = delay(conn, ConfigKey.FETCH_MISSING_RETRY_AFTER_DAYS)
        return asyncio.run(
            fetch_missing_hal_by_id(conn, ctx.logger, retry_after_days=retry_after_days)
        )


def _run_fetch_missing_scanr_by_hal_id(ctx: PhaseContext) -> PhaseMetrics:
    """Cherche dans ScanR, par hal-id, les documents repérés dans HAL ou OpenAlex et absents de ScanR."""
    from pipeline.ingestion.scanr.fetch_missing import fetch_missing_scanr_by_hal_id

    with ctx.open_tx() as conn:
        retry_after_days = delay(conn, ConfigKey.FETCH_MISSING_RETRY_AFTER_DAYS)
        return asyncio.run(
            fetch_missing_scanr_by_hal_id(conn, ctx.logger, retry_after_days=retry_after_days)
        )


def _run_fetch_missing_hal_by_nnt(ctx: PhaseContext) -> PhaseMetrics:
    """Cherche dans HAL, par NNT, les thèses soutenues de theses.fr sans document HAL."""
    from pipeline.ingestion.hal.fetch_missing import fetch_missing_hal_by_nnt

    with ctx.open_tx() as conn:
        retry_after_days = delay(conn, ConfigKey.FETCH_MISSING_RETRY_AFTER_DAYS)
        return asyncio.run(
            fetch_missing_hal_by_nnt(conn, ctx.logger, retry_after_days=retry_after_days)
        )


def _run_fetch_missing_theses_by_nnt(ctx: PhaseContext) -> PhaseMetrics:
    """Cherche dans theses.fr, par NNT, les thèses trouvées dans d'autres sources et absentes du staging theses.fr."""
    from pipeline.ingestion.theses.fetch_missing import fetch_missing_theses_by_nnt

    with ctx.open_tx() as conn:
        retry_after_days = delay(conn, ConfigKey.FETCH_MISSING_RETRY_AFTER_DAYS)
        return asyncio.run(
            fetch_missing_theses_by_nnt(conn, ctx.logger, retry_after_days=retry_after_days)
        )


def _run_fetch_missing_doi(ctx: PhaseContext, target: str) -> PhaseMetrics:
    doi_search = ADAPTERS[Source(target)].doi_search
    assert doi_search is not None, f"{target} : source interrogeable par DOI sans recherche"
    search = doi_search()
    options = ctx.options
    with ctx.open_tx() as conn:
        retry_after_days = delay(conn, ConfigKey.FETCH_MISSING_RETRY_AFTER_DAYS)
        limit = cap(conn, ConfigKey.FETCH_MISSING_MAX_PER_SOURCE)
        years = window_years(conn, start_year=options.start_year, year=options.year)
        return asyncio.run(
            fetch_missing_doi(
                conn,
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
    section: str,
    when: Callable[[PhaseContext], bool],
) -> Task:
    """Renvoie la tâche d'un canal de recherche, avec les lectures et écritures communes aux canaux : identifiants des publications du périmètre, cherchés dans les autres sources ; échecs retenus dans `failed_lookups`."""
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
        section=section,
        when=when,
        silent_when_empty=True,
    )


def _requested(source: str) -> Callable[[PhaseContext], bool]:
    return lambda ctx: source in ctx.options.sources


def _doi_targets(ctx: PhaseContext) -> set[str]:
    """Renvoie les sources cherchées par DOI : celles demandées, WoS seulement sur option."""
    options = ctx.options
    return set(
        select_targets(DOI_SEARCHABLE_SOURCES, options.sources, include_wos=options.include_wos)
    )


TASKS = (
    _channel(
        _HAL_BY_ID,
        network="hal",
        parallel_group="fetch_missing.hal_id",
        run=_run_fetch_missing_hal_by_id,
        section=_HAL_ID_SECTION,
        when=_requested("hal"),
    ),
    _channel(
        _SCANR_BY_HAL_ID,
        reads=("source_records.source_id",),
        network="scanr",
        parallel_group="fetch_missing.hal_id",
        run=_run_fetch_missing_scanr_by_hal_id,
        section=_HAL_ID_SECTION,
        when=_requested("scanr"),
    ),
    _channel(
        _HAL_BY_NNT,
        reads=("publications.doc_type",),
        previous_run=("publications.doc_type",),
        network="hal",
        parallel_group="fetch_missing.nnt",
        run=_run_fetch_missing_hal_by_nnt,
        section=_NNT_SECTION,
        when=lambda ctx: "hal" in ctx.options.sources and ctx.options.mode == "full",
    ),
    _channel(
        _THESES_BY_NNT,
        network="theses",
        parallel_group="fetch_missing.nnt",
        run=_run_fetch_missing_theses_by_nnt,
        section=_NNT_SECTION,
        when=_requested("theses"),
    ),
    *(
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
            parallel_group="fetch_missing.doi",
            run=lambda ctx, target=target: _run_fetch_missing_doi(ctx, target),
            section="Recherche par DOI des documents manquants dans chaque source",
            when=lambda ctx, target=target: target in _doi_targets(ctx),
        )
        for target in DOI_SEARCHABLE_SOURCES
    ),
)

_CHANNEL_KEYS = {
    _HAL_BY_ID: "hal-id",
    _SCANR_BY_HAL_ID: "hal-id ScanR",
    _HAL_BY_NNT: "NNT",
    _THESES_BY_NNT: "NNT theses.fr",
    **{_doi_task(target): target for target in DOI_SEARCHABLE_SOURCES},
}
"""Clé de chaque canal dans la table d'observabilité de la phase."""


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie la somme des métriques des canaux, avec la table des canaux interrogés."""
    metrics = PhaseMetrics()
    by_channel: dict[str, dict[str, float | None]] = {}
    for name, channel_metrics in by_task.items():
        metrics.merge(channel_metrics)
        if not skipped(channel_metrics):
            by_channel[_CHANNEL_KEYS[name]] = _summary(channel_metrics)
    if by_channel:
        metrics.details["table"] = {
            "rows": [{"key": channel, **summary} for channel, summary in by_channel.items()]
        }
    return metrics
