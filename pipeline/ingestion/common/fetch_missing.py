"""Phase `fetch_missing` : rattrapage des documents repérés dans une source mais absents d'une autre.

Une étape par source. Les sources sont interrogées en parallèle, et chaque source enchaîne ses recherches :

- **HAL** : les hal-id repérés dans OpenAlex et ScanR, puis, en mode `full`, les thèses de theses.fr sans document HAL (`pipeline.ingestion.hal.fetch_missing`), puis les DOI vus ailleurs ;
- **ScanR** : les hal-id repérés dans HAL et OpenAlex (`pipeline.ingestion.scanr.fetch_missing`), puis les DOI vus ailleurs ;
- **theses.fr** : les NNT repérés dans une autre source (`pipeline.ingestion.theses.fetch_missing`) ;
- **OPS** : les familles des numéros de brevet repérés dans une autre source (`pipeline.ingestion.ops.fetch_missing`) ;
- **OpenAlex, WoS, Crossref, DataCite** : les DOI vus ailleurs et absents de la source.

Au journal, chaque recherche a sa barre, libellée par la source et le type d'identifiant cherché. Une recherche sans identifiant à chercher écrit « rien à faire ».

Un identifiant cherché en vain est inscrit dans `failed_lookups`, et cherché de nouveau après le délai `fetch_missing_retry_after_days`. Auprès du registre qui l'attribue (HAL pour un hal-id, theses.fr pour un NNT), l'échec est définitif. Un DOI inconnu de doi.org (`dois.registered`) sort de la sélection. WoS est opt-in (`--include-wos`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Mapping

from domain.config import ConfigKey
from domain.sources.registry import DOI_SEARCHABLE_SOURCES, PROFILES, Source
from pipeline.graph import Step, Task
from pipeline.ingestion.adapters import adapter
from pipeline.ingestion.common.doi_search import fetch_missing_doi
from pipeline.ingestion.hal.fetch_missing import fetch_missing_hal_by_id, fetch_missing_hal_by_nnt
from pipeline.ingestion.ops.fetch_missing import fetch_missing_ops_by_number
from pipeline.ingestion.scanr.fetch_missing import fetch_missing_scanr_by_hal_id
from pipeline.ingestion.theses.fetch_missing import fetch_missing_theses_by_nnt
from pipeline.runtime.config import cap, delay, window_years
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import assemble_by_source

_HAL_BY_ID = "hal_by_id"
_SCANR_BY_HAL_ID = "scanr_by_hal_id"
_HAL_BY_NNT = "hal_by_nnt"
_THESES_BY_NNT = "theses_by_nnt"
_OPS_BY_NUMBER = "ops_by_number"


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


type ChannelRun = Callable[[PhaseContext, str], PhaseMetrics]
"""Exécution d'un canal : contexte de la phase, type d'identifiant cherché tel qu'affiché au journal."""


def _by_identifier(search: Callable[..., Coroutine[object, object, PhaseMetrics]]) -> ChannelRun:
    """Renvoie l'exécution d'une recherche par hal-id, NNT ou numéro de brevet, avec le délai avant de chercher de nouveau un identifiant introuvable."""

    def run(ctx: PhaseContext, scope: str) -> PhaseMetrics:
        with ctx.open_tx() as conn:
            retry_after_days = delay(conn, ConfigKey.FETCH_MISSING_RETRY_AFTER_DAYS)
            return asyncio.run(
                search(conn, ctx.logger, retry_after_days=retry_after_days, scope=scope)
            )

    return run


def _run_fetch_missing_doi(ctx: PhaseContext, scope: str, target: str) -> PhaseMetrics:
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
                scope=scope,
            )
        )


def _channel(
    name: str,
    *,
    reads: tuple[str, ...] = (),
    previous_run: tuple[str, ...] = (),
    network: str,
    identifier: str,
    run: ChannelRun,
    when: Callable[[PhaseContext], bool] | None = None,
) -> Task:
    """Renvoie la tâche d'un canal de recherche, exécutée quand le run interroge sa source et que `when` est remplie. `identifier` nomme le type d'identifiant cherché, au journal ; `run` le reçoit.

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
        parallel_group="sources",
        run=lambda ctx: run(ctx, identifier),
        label=f"par {identifier}",
        when=lambda ctx: network in ctx.options.queried_sources and (when is None or when(ctx)),
        silent_when_empty=True,
    )


_BY_DOI = {
    target: _channel(
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
        identifier="DOI",
        run=lambda ctx, scope, target=target: _run_fetch_missing_doi(ctx, scope, target),
    )
    for target in DOI_SEARCHABLE_SOURCES
}
"""Recherche par DOI dans chaque source interrogeable par DOI."""

_BY_SOURCE: dict[str, tuple[Task, ...]] = {
    Source.HAL: (
        _channel(
            _HAL_BY_ID,
            network="hal",
            identifier="hal-id",
            run=_by_identifier(fetch_missing_hal_by_id),
        ),
        _channel(
            _HAL_BY_NNT,
            reads=("publications.doc_type",),
            previous_run=("publications.doc_type",),
            network="hal",
            identifier="NNT",
            run=_by_identifier(fetch_missing_hal_by_nnt),
            when=lambda ctx: ctx.options.policy.hal_theses_by_nnt,
        ),
        _BY_DOI[Source.HAL],
    ),
    Source.SCANR: (
        _channel(
            _SCANR_BY_HAL_ID,
            reads=("source_records.source_id",),
            network="scanr",
            identifier="hal-id",
            run=_by_identifier(fetch_missing_scanr_by_hal_id),
        ),
        _BY_DOI[Source.SCANR],
    ),
    Source.THESES: (
        _channel(
            _THESES_BY_NNT,
            network="theses",
            identifier="NNT",
            run=_by_identifier(fetch_missing_theses_by_nnt),
        ),
    ),
    Source.OPS: (
        _channel(
            _OPS_BY_NUMBER,
            network="ops",
            identifier="n° brevet",
            run=_by_identifier(fetch_missing_ops_by_number),
        ),
    ),
    **{
        target: (channel,)
        for target, channel in _BY_DOI.items()
        if target not in (Source.HAL, Source.SCANR)
    },
}
"""Recherches de chaque source, dans l'ordre : une recherche par DOI dans HAL suit la recherche par hal-id, qui a déjà écrit ses documents dans `staging`."""


_SUMMARIES: dict[str, str] = {
    Source.HAL: "hal-id, NNT et DOI trouvés dans une autre source → documents absents de HAL",
    Source.SCANR: "hal-id et DOI trouvés dans une autre source → documents absents de ScanR",
    Source.THESES: "NNT trouvés dans une autre source → thèses absentes de theses.fr",
    Source.OPS: "numéros de brevet trouvés dans une autre source → familles de brevets absentes d'OPS",
    Source.OPENALEX: "DOI trouvés dans une autre source → documents absents d'OpenAlex",
    Source.WOS: "DOI trouvés dans une autre source → documents absents de WoS",
    Source.CROSSREF: "DOI trouvés dans une autre source → documents absents de Crossref",
    Source.DATACITE: "DOI trouvés dans une autre source → documents absents de DataCite",
}
"""Phrase d'entrées → sorties de l'étape de chaque source."""

STEPS = tuple(Step(str(source), _SUMMARIES[source], tasks) for source, tasks in _BY_SOURCE.items())

_CHANNEL_KEYS = {
    _HAL_BY_ID: "hal-id",
    _SCANR_BY_HAL_ID: "hal-id ScanR",
    _HAL_BY_NNT: "NNT",
    _THESES_BY_NNT: "NNT theses.fr",
    _OPS_BY_NUMBER: "numéro de brevet OPS",
    **{_doi_task(target): target for target in DOI_SEARCHABLE_SOURCES},
}
"""Clé de chaque canal dans la table d'observabilité de la phase."""


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie la somme des métriques des canaux, avec la table des canaux interrogés."""
    return assemble_by_source(by_task, _summary, key=_CHANNEL_KEYS.__getitem__)
