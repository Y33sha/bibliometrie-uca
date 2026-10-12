"""Phase `fetch_stale` : nouvelle lecture des documents de `staging` que le moissonnage n'a pas revus depuis `fetch_stale_after_days` jours. Nœuds `fetch_stale.<source>`.

Chaque document est relu **par son identifiant natif** (`staging.source_id`), avec ou sans DOI. Trois issues :

- document trouvé → écriture dans `staging` (`raw_data` réécrit si l'empreinte change, `last_seen_at` toujours mis à jour) ;
- absence confirmée (réponse valide, zéro document) → `disappeared_at` ;
- source indisponible (réseau, 429, réponse illisible) → rien, nouvelle tentative au run suivant.

Le délai étale la charge sans `LIMIT` : chaque passe ramasse seulement les documents qui viennent de le franchir. Seule la requête par identifiant natif est propre à chaque source (`StaleRefetch.fetch_by_native_id`).
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial

import httpx2
from sqlalchemy import Connection, text

from domain.sources.registry import ALL_SOURCES, ALL_SOURCES_SET as VALID_SOURCES
from domain.types import JsonValue
from infrastructure.sources.circuit_breaker import SourceCircuitBreaker
from infrastructure.sources.lookup import NOT_FOUND, UNAVAILABLE, LookupOutcome
from pipeline.context import Phase, PhaseContext
from pipeline.execution import credentials_missing, log, open_tx, under_circuit_breaker
from pipeline.fetch_pool import run_fetch_pool
from pipeline.libelles import DERNIERE_BRANCHE, branche_de_source
from pipeline.logging_scope import scoped_logger
from pipeline.metrics import PhaseMetrics
from pipeline.modes import MODES
from pipeline.progression import progression
from pipeline.signals import filter_configured, select_targets, timed_metrics
from pipeline.sources.staging import upsert_staging

COMMIT_EVERY = 50

# Dépendances techniques du phasage, injectées par le composition-root.
RefreshOne = Callable[[str, "list[int] | None"], PhaseMetrics]
"""Nouvelle lecture des documents d'une source, bornée à `years`. Rend des métriques portant déjà l'éventuel signal `source_unavailable`."""
CredentialsMissing = Callable[[str], "str | None"]
"""`(source) -> motif d'absence de credentials | None si configurée`."""
GetYearsForWindow = Callable[["int | None"], "list[int] | None"]
"""`(start_year) -> années de la fenêtre du run | None (tout l'historique)`."""


@dataclass(frozen=True)
class FetchStalePhase:
    refresh_one: RefreshOne
    credentials_missing: CredentialsMissing
    get_years_for_window: GetYearsForWindow

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Relit les documents anciens de chaque source configurée, dans la fenêtre d'années du run.

        La phase est sautée dans un mode dont la policy exclut `fetch_stale`. WoS est opt-in (`--include-wos`). Fenêtre d'années : `--year` cible une seule année, sinon `[start_year … courante]` ; `theses` ignore la borne large (tout l'historique des PPN), mais suit `--year`. Les sources non configurées sont sautées avec un signal `source_unconfigured`.
        """
        options, logger = ctx.options, ctx.logger
        metrics = PhaseMetrics()
        if not MODES[options.mode].fetch_stale:
            logger.info("%sSautée en mode %s", DERNIERE_BRANCHE, options.mode)
            return metrics
        targets = select_targets(
            ALL_SOURCES, options.sources or None, include_wos=options.include_wos
        )
        configured = filter_configured(
            targets,
            metrics,
            credentials_missing=self.credentials_missing,
            logger=logger,
            phase="fetch_stale",
        )

        year = options.year
        years_default = [int(year)] if year else self.get_years_for_window(options.start_year)
        years_theses = [int(year)] if year else None

        by_source: dict[str, dict[str, float]] = {}
        for target in configured:
            row_years = years_theses if target == "theses" else years_default
            source_metrics, duration = timed_metrics(partial(self.refresh_one, target, row_years))
            metrics.merge(source_metrics)
            by_source[target] = {
                "interrogated": source_metrics.total,
                "refreshed": source_metrics.updated,
                "unchanged": source_metrics.unchanged,
                "disappeared": source_metrics.extras.get("disappeared", 0),
                "duration_s": round(duration, 1),
            }

        if by_source:
            metrics.details["table"] = {
                "rows": [{"key": source, **summary} for source, summary in by_source.items()]
            }
        return metrics


@dataclass(frozen=True, slots=True)
class FetchedRecord:
    """Document relu dans la source : payload brut et DOI."""

    doi: str | None
    raw_data: Mapping[str, JsonValue]


type FetchOutcome = LookupOutcome[FetchedRecord]


class StaleRefetch(ABC):
    """Nouvelle lecture d'un document d'une source par son identifiant natif.

    Les sous-classes fixent `source_key`, `max_concurrent`, `request_delay_s` et implémentent `fetch_by_native_id`.
    """

    source_key: str
    max_concurrent: int  # plafond de requêtes simultanées, sous le rate-limit de l'API
    request_delay_s: float = 0.0  # pause par worker après chaque requête

    @abstractmethod
    async def fetch_by_native_id(
        self, client: httpx2.AsyncClient, source_id: str
    ) -> FetchOutcome: ...


# Filtre année (`{year_clause}`) : `pub_year` vient de `source_publications` (LEFT JOIN ; NULL si absent, conservé).
_STALE_ROWS_SQL_TEMPLATE = """
    SELECT s.source_id
    FROM staging s
    LEFT JOIN source_publications sp
      ON sp.source = s.source AND sp.source_id = s.source_id
    WHERE s.source = CAST(:source AS source_type)
      AND s.disappeared_at IS NULL
      AND s.last_seen_at < now() - make_interval(days => :days)
      {year_clause}
    ORDER BY s.id
"""

_SET_DISAPPEARED_SQL = text(
    """
    UPDATE staging SET disappeared_at = now()
    WHERE source = CAST(:source AS source_type) AND source_id = :source_id
      AND disappeared_at IS NULL
    """
)


def get_stale_source_ids(
    conn: Connection, source: str, years: list[int] | None = None, *, after_days: int
) -> list[str]:
    """Identifiants natifs des documents de `source` dont `last_seen_at` date de plus de `after_days` jours, hors documents disparus.

    `years` borne la sélection à la fenêtre d'années du run, jointe depuis `source_publications.pub_year` : un run sur une période glissante relit seulement les documents de ses propres années. `None` = aucune borne.
    """
    if source not in VALID_SOURCES:
        raise ValueError(f"Source inconnue : {source}. Valides : {', '.join(VALID_SOURCES)}")
    params: dict[str, object] = {"source": source, "days": after_days}
    year_clause = ""
    if years is not None:
        year_clause = "AND (sp.pub_year IS NULL OR sp.pub_year = ANY(:years))"
        params["years"] = list(years)
    sql = text(_STALE_ROWS_SQL_TEMPLATE.format(year_clause=year_clause))
    return list(conn.execute(sql, params).scalars())


def set_disappeared(conn: Connection, source: str, source_id: str) -> None:
    """Pose `disappeared_at` sur le document `(source, source_id)` confirmé absent. Ne commite pas."""
    conn.execute(_SET_DISAPPEARED_SQL, {"source": source, "source_id": source_id})


async def refresh(
    conn: Connection,
    refetch: StaleRefetch,
    log: logging.Logger,
    *,
    after_days: int,
    years: list[int] | None = None,
    breaker: SourceCircuitBreaker | None = None,
) -> PhaseMetrics:
    """Relit par identifiant natif les documents de la source de `refetch` non revus depuis `after_days` jours.

    `years` borne la sélection à la fenêtre d'années du run (via `source_publications.pub_year`) ; `None` = tous les documents anciens de la source.

    `updated` = `raw_data` réécrit (empreinte changée) ; `unchanged` = document identique (seul `last_seen_at` mis à jour) ; `errors` = source indisponible ; `extras["disappeared"]` = absences confirmées marquées `disappeared_at`.
    """
    source = refetch.source_key
    slog = scoped_logger(log, source)
    stale = get_stale_source_ids(conn, source, years, after_days=after_days)
    total = len(stale)

    metrics = PhaseMetrics(seen=total)
    if total == 0:
        return metrics

    processed = 0

    async def _fetch(client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        try:
            outcome = await refetch.fetch_by_native_id(client, source_id)
        except Exception as e:
            # Breaker déclenché pendant la requête : abandon silencieux, le journal le signale une fois après le pool.
            if not (breaker is not None and breaker.tripped):
                slog.error("erreur sur %s : %s", source_id, e)
            outcome = UNAVAILABLE
        if refetch.request_delay_s:
            await asyncio.sleep(refetch.request_delay_s)
        return outcome

    with progression(total, branche_de_source(source), slog, compte_retenus=True) as avancement:

        def _write(conn: Connection, source_id: str, outcome: FetchOutcome) -> None:
            nonlocal processed
            if outcome is UNAVAILABLE:
                metrics.add(errors=1)
            elif outcome is NOT_FOUND:
                set_disappeared(conn, source, source_id)
                metrics.add(disappeared=1)
            else:
                assert isinstance(outcome, FetchedRecord)
                _, changed = upsert_staging(
                    conn,
                    source=source,
                    source_id=source_id,
                    doi=outcome.doi,
                    raw_data=outcome.raw_data,
                )
                metrics.add(updated=1) if changed else metrics.add(unchanged=1)
                avancement.retient()
            processed += 1
            avancement.avance()

        await run_fetch_pool(
            stale,
            conn,
            max_concurrent=refetch.max_concurrent,
            commit_every=COMMIT_EVERY,
            fetch=_fetch,
            write=_write,
            should_continue=lambda: breaker is None or not breaker.tripped,
        )

    if breaker is not None and breaker.tripped:
        slog.warning(
            "indisponible (429/5xx répétés) — abandon, %d/%d documents traités, reste au prochain run",
            processed,
            total,
        )
    return metrics


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    """Rafraîchit les rows à `last_seen_at` ancien et marque les disparues.

    Chaque row est réinterrogée par son identifiant natif (`staging.source_id`), avec ou sans DOI : trouvée, son `last_seen_at` et son `raw_data` sont rafraîchis ; absente de sa source, elle reçoit un `disappeared_at` ; sur échec réseau, elle attend le run suivant. Le délai `fetch_stale_after_days` étale la charge, chaque passe ramassant seulement les rows qui viennent de le franchir.

    Le mode `daily` saute la phase. La fenêtre d'années du run (`start_year`/`year`, via `source_publications.pub_year`) borne le rafraîchissement aux années que le run moissonne. `theses` ramène tout son historique, comme à l'extraction, sauf sous `--year`. WoS est opt-in (`--include-wos`).
    """

    return FetchStalePhase(
        refresh_one=_run_fetch_stale,
        credentials_missing=credentials_missing,
        get_years_for_window=_get_years_for_window,
    )


def _get_years_for_window(start_year: int | None) -> list[int] | None:
    """Années de la fenêtre du run, de `start_year` à l'année courante."""
    from infrastructure.sources.config import get_years

    with open_tx() as conn:
        return get_years(conn, start_year)


def _make_refetch(source: str) -> StaleRefetch:
    """Construit la nouvelle lecture par identifiant natif d'une source."""
    from pipeline.sources.crossref.fetch_stale import CrossrefStaleRefetch
    from pipeline.sources.datacite.fetch_stale import DataciteStaleRefetch
    from pipeline.sources.hal.fetch_stale import HalStaleRefetch
    from pipeline.sources.openalex.fetch_stale import OpenalexStaleRefetch
    from pipeline.sources.scanr.fetch_stale import ScanrStaleRefetch
    from pipeline.sources.theses.fetch_stale import ThesesStaleRefetch
    from pipeline.sources.wos.fetch_stale import WosStaleRefetch

    refetches: dict[str, type[StaleRefetch]] = {
        "hal": HalStaleRefetch,
        "openalex": OpenalexStaleRefetch,
        "wos": WosStaleRefetch,
        "scanr": ScanrStaleRefetch,
        "theses": ThesesStaleRefetch,
        "crossref": CrossrefStaleRefetch,
        "datacite": DataciteStaleRefetch,
    }
    return refetches[source]()


def _run_fetch_stale(target: str, years: list[int] | None) -> PhaseMetrics:
    """Refetch par id natif des rows stale d'une source : trouvé → bump, absence → disappeared.

    `years` borne le refresh à la fenêtre d'années du run (None = tout le stale).
    """
    from infrastructure.sources.config import get_fetch_stale_after_days

    refetch = _make_refetch(target)
    with open_tx() as conn:
        after_days = get_fetch_stale_after_days(conn)
        return under_circuit_breaker(
            target,
            lambda breaker: asyncio.run(
                refresh(conn, refetch, log, after_days=after_days, years=years, breaker=breaker)
            ),
            phase="fetch_stale",
            logger=log,
        )
