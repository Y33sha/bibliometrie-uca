"""Recherche de documents dans une source par identifiant : boucle commune des phases `fetch_missing`, `fetch_stale` et `fetch_truncated`.

Un canal (`LookupChannel`) dit comment interroger la source pour un lot d'identifiants, comment écrire un document trouvé, et ce que devient un identifiant dont la source confirme l'absence. `look_up` interroge les lots en parallèle (`run_fetch_pool`), écrit les documents trouvés, range les absents et compte les issues. Un lot que la source ne sert pas attend le run suivant. Le pool s'arrête quand le circuit-breaker de la source coupe ; l'accès à la source le signale.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field

import httpx2
from sqlalchemy import Connection

from domain.types import JsonValue
from pipeline.http.circuit_breaker import source_tripped
from pipeline.http.fetch_pool import run_fetch_pool
from pipeline.http.lookup import UNAVAILABLE, LookupOutcome, NotFound, Unavailable
from pipeline.ingestion.common.staging import StagingStore, UpsertOutcome
from pipeline.runtime.observability.log_format import source_branch
from pipeline.runtime.observability.logging_scope import scoped_logger
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress

# Identifiants écrits entre deux commits.
COMMIT_EVERY = 50


@dataclass(frozen=True, slots=True)
class LookupBatch:
    """Réponse de la source à un lot d'identifiants : documents trouvés, identifiants dont la source confirme l'absence. Un identifiant du lot présent dans aucune des deux listes attend le run suivant."""

    records: list[Mapping[str, JsonValue]] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)


type Fetch = Callable[[httpx2.AsyncClient, list[str]], Awaitable[LookupBatch | Unavailable]]
"""Interroge la source pour un lot d'identifiants."""

type Stage = Callable[[StagingStore, Mapping[str, JsonValue]], UpsertOutcome | None]
"""Écrit un document trouvé dans `staging`. Rend `None` pour un document sans identifiant, qui n'est pas écrit."""


def one_at_a_time(
    fetch_one: Callable[
        [httpx2.AsyncClient, str], Awaitable[LookupOutcome[Mapping[str, JsonValue]]]
    ],
) -> Fetch:
    """Requête d'un lot d'un seul identifiant, par `fetch_one` : document trouvé, absence confirmée, ou source indisponible."""

    async def fetch(client: httpx2.AsyncClient, keys: list[str]) -> LookupBatch | Unavailable:
        (key,) = keys
        outcome = await fetch_one(client, key)
        if isinstance(outcome, Unavailable):
            return UNAVAILABLE
        if isinstance(outcome, NotFound):
            return LookupBatch(absent=[key])
        return LookupBatch(records=[outcome])

    return fetch


@dataclass(frozen=True)
class LookupChannel:
    """Recherche par identifiant dans une source."""

    source: str
    fetch: Fetch
    on_absent: Callable[[Connection, str], None]
    """Ce que devient un identifiant dont la source confirme l'absence. Ne commite pas."""
    stage: Stage | None = None
    """`None` : la source rend seulement la présence des identifiants, sans document à écrire."""
    absent_metric: str = "not_found"
    """Compteur des identifiants absents."""
    batch_size: int = 1
    max_concurrent: int = 1
    shown: bool = True
    """La recherche a sa barre de progression. `False` : une vérification qui prolonge une autre recherche, sous la barre de celle-ci."""


async def look_up(
    conn: Connection, log: logging.Logger, channel: LookupChannel, keys: Sequence[str]
) -> PhaseMetrics:
    """Cherche les identifiants dans la source du canal, écrit les documents trouvés et range les absents.

    Les compteurs rendus : identifiants cherchés (`total`), documents écrits (`new`, `updated`, `unchanged`), identifiants des lots que la source n'a pas servis (`errors`), identifiants absents (compteur du canal). La barre compte les documents trouvés.
    """
    metrics = PhaseMetrics(seen=len(keys))
    if not keys:
        return metrics
    slog = scoped_logger(log, channel.source)
    size = channel.batch_size
    batches = [list(keys[i : i + size]) for i in range(0, len(keys), size)]

    async def _fetch(client: httpx2.AsyncClient, batch: list[str]) -> LookupBatch | Unavailable:
        try:
            result = await channel.fetch(client, batch)
        except Exception as e:
            # Circuit-breaker coupé pendant la requête : l'accès à la source le signale une fois.
            if not source_tripped():
                slog.error("erreur sur %s : %s", ", ".join(batch), e)
            result = UNAVAILABLE
        return result

    progress = (
        track_progress(len(keys), source_branch(channel.source), slog, count_kept=True)
        if channel.shown
        else nullcontext(_Unshown())
    )
    with progress as bar:

        def _write(conn: Connection, batch: list[str], result: LookupBatch | Unavailable) -> None:
            bar.advance(len(batch))
            if isinstance(result, Unavailable):
                metrics.add(errors=len(batch))
                return
            if channel.stage is not None:
                bar.keep(_stage(channel.stage, StagingStore(conn), result.records, metrics))
            for key in result.absent:
                channel.on_absent(conn, key)
                metrics.add(**{channel.absent_metric: 1})

        await run_fetch_pool(
            batches,
            conn,
            max_concurrent=channel.max_concurrent,
            commit_every=max(1, COMMIT_EVERY // size),
            fetch=_fetch,
            write=_write,
        )

    return metrics


class _Unshown:
    """Avancement d'une recherche sans barre."""

    def advance(self, n: int = 1) -> None:
        pass

    def keep(self, n: int = 1) -> None:
        pass


def _stage(
    stage: Stage,
    staging: StagingStore,
    records: list[Mapping[str, JsonValue]],
    metrics: PhaseMetrics,
) -> int:
    """Écrit `records` par `stage`, les compte dans `metrics`, et rend le nombre de documents écrits."""
    written = 0
    for record in records:
        match stage(staging, record):
            case UpsertOutcome.NEW:
                metrics.add(new=1)
            case UpsertOutcome.UPDATED:
                metrics.add(updated=1)
            case UpsertOutcome.UNCHANGED:
                metrics.add(unchanged=1)
            case None:
                continue
        written += 1
    return written
