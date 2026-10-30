"""Éditeur de chaque préfixe DOI, une étape par agence d'enregistrement (phase `publishing`).

L'étape Crossref interroge `api.crossref.org/prefixes` pour les préfixes d'agence Crossref ou inconnue. L'étape DataCite interroge `api.datacite.org/prefixes` pour les préfixes d'agence DataCite, et pour ceux d'agence inconnue absents de Crossref. Chaque étape renseigne les métadonnées (`publisher_*`, `crossref_member_id`, `client_*`, `datacite_client_symbol`) et corrige l'agence d'un préfixe inconnu trouvé. Elle trouve ou crée ensuite l'éditeur parmi les formes de nom (`publisher_name_forms`), et l'attache au préfixe. Après réponse de l'API, le préfixe est marqué vu par l'agence (`crossref_checked_at`, `datacite_checked_at`). Si l'API est indisponible, le préfixe attend le run suivant.

Les requêtes `/prefixes` sont concurrentes (`run_fetch_pool`). Les écritures, création d'éditeurs comprise, sont sérialisées. Les clients HTTP sont injectés en callables.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx2
from sqlalchemy import Connection

from domain.normalize import normalize_text, to_plain_text
from pipeline.http.circuit_breaker import source_tripped
from pipeline.http.fetch_pool import run_fetch_pool
from pipeline.http.lookup import UNAVAILABLE, LookupOutcome, NotFound, Unavailable
from pipeline.runtime.observability.log_format import BRANCH, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress
from pipeline.transformation.publishing.doi_prefixes import (
    Agency,
    DoiPrefixStore,
    PendingPublisherPrefix,
)
from pipeline.transformation.publishing.find_or_create import match_or_create_publisher
from pipeline.transformation.publishing.publishers.store import PublisherStore

LABELS: dict[Agency, str] = {
    "Crossref": "Éditeurs des préfixes DOI Crossref",
    "DataCite": "Éditeurs des préfixes DOI DataCite",
}
"""Libellé de chaque étape dans le journal de la phase."""

MAX_CONCURRENT = 3
"""Requêtes `/prefixes` simultanées, sous les plafonds des pools polis Crossref et DataCite."""

COMMIT_EVERY = 50

type FetchCrossrefPrefixFn = Callable[
    [httpx2.AsyncClient, str, str | None], Awaitable[LookupOutcome[tuple[str, int | None]]]
]
"""Signature : `(client, prefix, sample_doi) -> (publisher_name, member_id) | NOT_FOUND | UNAVAILABLE`."""

type FetchDataCitePrefixFn = Callable[
    [httpx2.AsyncClient, str], Awaitable[LookupOutcome[tuple[str, str, str]]]
]
"""Signature : `(client, prefix) -> (provider_name, client_name, client_symbol) | NOT_FOUND | UNAVAILABLE`."""

type _Ask = Callable[
    [httpx2.AsyncClient, PendingPublisherPrefix], Awaitable[_PrefixAnswer | Unavailable]
]


@dataclass(frozen=True)
class _PrefixAnswer:
    """Réponse de `/prefixes` pour un préfixe."""

    ra: str
    """Agence retenue."""
    crossref: tuple[str, int | None] | None = None
    """Informations de Crossref, si le préfixe est présent chez Crossref."""
    datacite: tuple[str, str, str] | None = None
    """Informations de DataCite, si le préfixe est présent chez DataCite."""


def run_resolve_crossref_publishers(
    conn: Connection,
    log: logging.Logger,
    *,
    prefix_store: DoiPrefixStore,
    publisher_store: PublisherStore,
    fetch_prefix_fn: FetchCrossrefPrefixFn,
) -> PhaseMetrics:
    """Attache l'éditeur Crossref des préfixes en attente. Un DOI du préfixe, lu avant l'appel, sert à retrouver le membre déposant d'un compte sans dépôt."""

    async def ask(
        client: httpx2.AsyncClient, row: PendingPublisherPrefix
    ) -> _PrefixAnswer | Unavailable:
        answer = await fetch_prefix_fn(client, row.prefix, row.sample_doi)
        if isinstance(answer, Unavailable):
            return UNAVAILABLE
        if isinstance(answer, NotFound):
            return _PrefixAnswer(row.ra)
        return _PrefixAnswer("Crossref", crossref=answer)

    def prepare(conn: Connection, row: PendingPublisherPrefix) -> PendingPublisherPrefix:  # noqa: ARG001
        return row._replace(sample_doi=prefix_store.find_doi_with_prefix(row.prefix))

    return _resolve(conn, log, "Crossref", ask, prepare, prefix_store, publisher_store)


def run_resolve_datacite_publishers(
    conn: Connection,
    log: logging.Logger,
    *,
    prefix_store: DoiPrefixStore,
    publisher_store: PublisherStore,
    fetch_prefix_fn: FetchDataCitePrefixFn,
) -> PhaseMetrics:
    """Attache le provider DataCite des préfixes en attente, et retient le repository déposant des DOI."""

    async def ask(
        client: httpx2.AsyncClient, row: PendingPublisherPrefix
    ) -> _PrefixAnswer | Unavailable:
        answer = await fetch_prefix_fn(client, row.prefix)
        if isinstance(answer, Unavailable):
            return UNAVAILABLE
        if isinstance(answer, NotFound):
            return _PrefixAnswer(row.ra)
        return _PrefixAnswer("DataCite", datacite=answer)

    return _resolve(conn, log, "DataCite", ask, None, prefix_store, publisher_store)


def _resolve(
    conn: Connection,
    log: logging.Logger,
    agency: Agency,
    ask: _Ask,
    prepare: Callable[[Connection, PendingPublisherPrefix], PendingPublisherPrefix] | None,
    prefix_store: DoiPrefixStore,
    publisher_store: PublisherStore,
) -> PhaseMetrics:
    """Traite les préfixes en attente auprès de l'agence. S'arrête quand le circuit-breaker de la source coupe.

    Returns:
        Métriques : `total`, préfixes traités ; `errors`, préfixes laissés en attente faute de réponse ; `extras`, `publisher_matched` / `publisher_created` / `no_publisher` (préfixe inconnu de l'agence).
    """
    metrics = PhaseMetrics()
    rows = prefix_store.get_prefixes_pending_publisher(agency)
    if not rows:
        return metrics
    with track_progress(len(rows), f"{BRANCH}{LABELS[agency]}", log, erase=True) as progress:
        # Nom déjà stocké : rattachement direct, sans requête.
        for row in rows:
            if row.publisher_name_normalized is not None:
                _attach(
                    row,
                    agency,
                    row.publisher_name_raw,
                    row.publisher_name_normalized,
                    metrics,
                    log,
                    prefix_store,
                    publisher_store,
                )
                progress.advance()
        to_fetch = [row for row in rows if row.publisher_name_normalized is None]

        def _write(
            conn: Connection,  # noqa: ARG001
            row: PendingPublisherPrefix,
            answer: _PrefixAnswer | Unavailable,
        ) -> None:
            if isinstance(answer, Unavailable):
                metrics.add(seen=1, errors=1)
                log.info(
                    "%s → API indisponible, repris au prochain run",
                    row.prefix,
                    extra={"detail": True},
                )
            else:
                name_raw, name_normalized = _store_publisher_metadata(row, answer, prefix_store)
                _attach(
                    row,
                    agency,
                    name_raw,
                    name_normalized,
                    metrics,
                    log,
                    prefix_store,
                    publisher_store,
                )
            progress.advance()

        asyncio.run(
            run_fetch_pool(
                to_fetch,
                conn,
                max_concurrent=MAX_CONCURRENT,
                commit_every=COMMIT_EVERY,
                fetch=ask,
                write=_write,
                prepare=prepare,
            )
        )
    if source_tripped():
        log.warning("resolve_publishers : circuit-breaker %s coupé, arrêt", agency)

    metrics.report = (
        f"{quantity(metrics.total, 'préfixe')} : "
        f"{quantity(metrics.extras.get('publisher_matched', 0), 'éditeur reconnu', 'éditeurs reconnus')}, "
        f"{quantity(metrics.extras.get('publisher_created', 0), 'créé', 'créés')}, "
        f"{quantity(metrics.extras.get('no_publisher', 0), 'inconnu', 'inconnus')}"
    )
    if metrics.errors:
        metrics.report += f", {quantity(metrics.errors, 'reporté', 'reportés')}"
    return metrics


def _store_publisher_metadata(
    row: PendingPublisherPrefix, answer: _PrefixAnswer, prefix_store: DoiPrefixStore
) -> tuple[str | None, str | None]:
    """Persiste les métadonnées de la réponse `/prefixes` et l'agence retenue. Renvoie `(name_raw, name_normalized)`."""
    publisher_name_raw: str | None = None
    publisher_name_normalized: str | None = None
    crossref_member_id: int | None = None
    client_name_raw: str | None = None
    client_name_normalized: str | None = None
    datacite_client_symbol: str | None = None

    # Le nom stocké et le nom normalisé dérivent du même texte brut.
    if answer.crossref is not None:
        publisher_name_raw, crossref_member_id = answer.crossref
        publisher_name_raw = to_plain_text(publisher_name_raw)
        publisher_name_normalized = normalize_text(publisher_name_raw) or None
    elif answer.datacite is not None:
        publisher_name_raw, client_name_raw, datacite_client_symbol = answer.datacite
        publisher_name_raw = to_plain_text(publisher_name_raw)
        client_name_raw = to_plain_text(client_name_raw)
        publisher_name_normalized = normalize_text(publisher_name_raw) or None
        client_name_normalized = normalize_text(client_name_raw) or None

    # Même sans nom, les métadonnées et l'agence corrigée s'écrivent : le préfixe sort de l'attente.
    prefix_store.set_prefix_publisher_metadata(
        prefix=row.prefix,
        ra=answer.ra,
        publisher_name_raw=publisher_name_raw,
        publisher_name_normalized=publisher_name_normalized,
        crossref_member_id=crossref_member_id,
        client_name_raw=client_name_raw,
        client_name_normalized=client_name_normalized,
        datacite_client_symbol=datacite_client_symbol,
    )
    return publisher_name_raw, publisher_name_normalized


def _attach(
    row: PendingPublisherPrefix,
    agency: Agency,
    name_raw: str | None,
    name_normalized: str | None,
    metrics: PhaseMetrics,
    log: logging.Logger,
    prefix_store: DoiPrefixStore,
    publisher_store: PublisherStore,
) -> None:
    """Rattache l'éditeur nommé, le crée au besoin, et marque le préfixe vu par l'agence."""
    metrics.add(seen=1)
    matched = (
        match_or_create_publisher(name_raw, repo=publisher_store)
        if name_raw and name_normalized is not None
        else None
    )
    if matched is not None:
        publisher_id, created = matched
        prefix_store.update_publisher_id(row.prefix, publisher_id)
        metrics.add(**{"publisher_created" if created else "publisher_matched": 1})
        # Ligne de détail : le terminal la masque, le journal la garde.
        log.info(
            "%s → “%s”%s",
            row.prefix,
            name_raw,
            " (nouveau)" if created else "",
            extra={"detail": True},
        )
    else:
        metrics.add(no_publisher=1)
        log.info("%s → éditeur inconnu de %s", row.prefix, agency, extra={"detail": True})

    prefix_store.mark_checked(row.prefix, agency)
