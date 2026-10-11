"""Volet publisher de `publishers_journals` : préfixe DOI → éditeur / repository, après `normalize`.

Pour chaque row en attente (`publisher_id IS NULL` et `publisher_checked_at IS NULL`, RA gérée), interroge `/prefixes` en routant par Registration Agency (`Crossref`/`DataCite` → l'endpoint correspondant ; `unknown` → tente les deux et corrige la RA), renseigne les métadonnées (`publisher_*`, `crossref_member_id`, `client_*`, `datacite_client_symbol`), puis match ou crée le publisher contre `publisher_name_forms` et l'attache. Une row dont le préfixe est trouvé ou absent est marquée vérifiée (`publisher_checked_at`) et n'est plus reprise. Une row dont l'API est indisponible reste en attente du run suivant. Placé après `normalize` pour matcher contre les publishers déjà créés par les sources.

Les requêtes `/prefixes` partent en concurrence via `run_fetch_pool` ; les écritures, dont la création d'éditeurs, restent sérialisées. La Registration Agency de chaque préfixe est posée en amont par la phase `resolve_ra`. Les clients HTTP (`api.crossref.org/prefixes`, `api.datacite.org/prefixes`) sont injectés en callables, pour la testabilité et l'étanchéité DDD (`application` ne dépend pas d'`infrastructure`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx2
from sqlalchemy import Connection

from application.pipeline._fetch_pool import run_fetch_pool
from application.ports.pipeline.circuit_breaker import CircuitBreaker
from application.ports.pipeline.doi_prefixes import (
    DoiPrefixesQueries,
    PendingPublisherPrefix,
)
from application.ports.pipeline.lookup import UNAVAILABLE, LookupOutcome, NotFound, Unavailable
from application.ports.pipeline.publishers import PublisherFindOrCreateQueries
from application.services.publishers.core import match_or_create_publisher
from domain.normalize import normalize_text, to_plain_text
from pipeline.libelles import BRANCHE, accord
from pipeline.metrics import PhaseMetrics
from pipeline.progression import progression

LIBELLE = "Éditeurs des préfixes DOI"
"""Libellé de la sous-étape dans le journal de la phase."""

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


@dataclass(frozen=True)
class _PrefixAnswer:
    """Réponse de `/prefixes` pour un préfixe : RA retenue, et les informations de l'agence qui le connaît (aucune si le préfixe est absent des deux)."""

    ra: str
    crossref: tuple[str, int | None] | None = None
    datacite: tuple[str, str, str] | None = None


def run_resolve_publishers(
    conn: Connection,
    log: logging.Logger,
    *,
    repo: DoiPrefixesQueries,
    publisher_repo: PublisherFindOrCreateQueries,
    fetch_crossref_prefix_fn: FetchCrossrefPrefixFn,
    fetch_datacite_prefix_fn: FetchDataCitePrefixFn,
    breaker: CircuitBreaker | None = None,
) -> PhaseMetrics:
    """Détermine et attache le publisher des préfixes en attente via `/prefixes`.

    `total` = préfixes traités ; `errors` = préfixes laissés en attente faute de réponse ; `extras` = `publisher_matched` / `publisher_created` / `no_publisher` (RA gérée mais préfixe inconnu de `/prefixes`). S'arrête si le `breaker` a tripé.
    """
    metrics = PhaseMetrics()
    rows = repo.get_prefixes_pending_publisher()
    if not rows:
        return metrics
    with progression(len(rows), f"{BRANCHE}{LIBELLE}", log, efface=True) as avancement:
        # Nom déjà stocké : rattachement direct, sans requête.
        for row in rows:
            if row.publisher_name_normalized is not None:
                _attach(
                    row,
                    row.publisher_name_raw,
                    row.publisher_name_normalized,
                    metrics,
                    log,
                    repo,
                    publisher_repo,
                )
                avancement.avance()
        to_fetch = [row for row in rows if row.publisher_name_normalized is None]

        def _prepare(conn: Connection, row: PendingPublisherPrefix) -> PendingPublisherPrefix:  # noqa: ARG001
            # Le DOI témoin sert au seul cas du compte sans dépôt, mais se lit avant l'appel : la recherche
            # d'un DOI du préfixe est une requête, l'appel HTTP en est déjà une de plus.
            if row.ra == "DataCite":
                return row
            return row._replace(sample_doi=repo.find_doi_with_prefix(row.prefix))

        async def _fetch(
            client: httpx2.AsyncClient, row: PendingPublisherPrefix
        ) -> _PrefixAnswer | Unavailable:
            return await _ask_prefixes(
                client, row, fetch_crossref_prefix_fn, fetch_datacite_prefix_fn
            )

        def _write(
            conn: Connection,  # noqa: ARG001
            row: PendingPublisherPrefix,
            answer: _PrefixAnswer | Unavailable,
        ) -> None:
            if isinstance(answer, Unavailable):
                metrics.add(total=1, errors=1)
                log.info(
                    "%s → API indisponible, repris au prochain run",
                    row.prefix,
                    extra={"detail": True},
                )
            else:
                name_raw, name_normalized = _store_publisher_metadata(row, answer, repo)
                _attach(row, name_raw, name_normalized, metrics, log, repo, publisher_repo)
            avancement.avance()

        asyncio.run(
            run_fetch_pool(
                to_fetch,
                conn,
                max_concurrent=MAX_CONCURRENT,
                commit_every=COMMIT_EVERY,
                fetch=_fetch,
                write=_write,
                should_continue=lambda: breaker is None or not breaker.tripped,
                prepare=_prepare,
            )
        )
    if breaker is not None and breaker.tripped:
        log.warning("resolve_publishers : circuit-breaker tripé, arrêt")

    metrics.resume = (
        f"{accord(metrics.total, 'préfixe')} : "
        f"{accord(metrics.extras.get('publisher_matched', 0), 'éditeur reconnu', 'éditeurs reconnus')}, "
        f"{accord(metrics.extras.get('publisher_created', 0), 'créé', 'créés')}, "
        f"{accord(metrics.extras.get('no_publisher', 0), 'inconnu', 'inconnus')}"
    )
    if metrics.errors:
        metrics.resume += f", {accord(metrics.errors, 'reporté', 'reportés')}"
    return metrics


async def _ask_prefixes(
    client: httpx2.AsyncClient,
    row: PendingPublisherPrefix,
    fetch_crossref_prefix_fn: FetchCrossrefPrefixFn,
    fetch_datacite_prefix_fn: FetchDataCitePrefixFn,
) -> _PrefixAnswer | Unavailable:
    """Interroge `/prefixes` selon la RA de la row. RA `unknown` : Crossref, puis DataCite si Crossref ignore le préfixe ; la RA est corrigée d'après l'agence qui répond."""
    if row.ra in ("Crossref", "unknown"):
        crossref = await fetch_crossref_prefix_fn(client, row.prefix, row.sample_doi)
        if isinstance(crossref, Unavailable):
            return UNAVAILABLE
        if not isinstance(crossref, NotFound):
            return _PrefixAnswer("Crossref", crossref=crossref)
        if row.ra == "Crossref":
            return _PrefixAnswer(row.ra)
    datacite = await fetch_datacite_prefix_fn(client, row.prefix)
    if isinstance(datacite, Unavailable):
        return UNAVAILABLE
    if isinstance(datacite, NotFound):
        return _PrefixAnswer(row.ra)
    return _PrefixAnswer("DataCite", datacite=datacite)


def _store_publisher_metadata(
    row: PendingPublisherPrefix, answer: _PrefixAnswer, repo: DoiPrefixesQueries
) -> tuple[str | None, str | None]:
    """Persiste les métadonnées de la réponse `/prefixes` et la RA retenue. Retourne `(name_raw, name_normalized)`."""
    publisher_name_raw: str | None = None
    publisher_name_normalized: str | None = None
    crossref_member_id: int | None = None
    client_name_raw: str | None = None
    client_name_normalized: str | None = None
    datacite_client_symbol: str | None = None

    # Noms mis à plat une fois : servent de nom stocké et de base au nom normalisé (clé de
    # rapprochement), pour que les deux dérivent de la même valeur (cf. `find_or_create_journal`).
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

    # Persiste même si le nom est vide : la row sera marquée vérifiée, donc pas de re-fetch — autant garder la RA corrigée et les colonnes à jour.
    repo.set_prefix_publisher_metadata(
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
    name_raw: str | None,
    name_normalized: str | None,
    metrics: PhaseMetrics,
    log: logging.Logger,
    repo: DoiPrefixesQueries,
    publisher_repo: PublisherFindOrCreateQueries,
) -> None:
    """Rattache l'éditeur nommé, le crée au besoin, et marque le préfixe vérifié."""
    metrics.add(total=1)
    matched = (
        match_or_create_publisher(name_raw, repo=publisher_repo)
        if name_raw and name_normalized is not None
        else None
    )
    if matched is not None:
        publisher_id, created = matched
        repo.update_publisher_id(row.prefix, publisher_id)
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
        log.info("%s → éditeur inconnu de %s", row.prefix, row.ra, extra={"detail": True})

    repo.mark_publisher_checked(row.prefix)
