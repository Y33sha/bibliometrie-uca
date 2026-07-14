"""Volet publisher de `publishers_journals` : préfixe DOI → éditeur / repository, après `normalize`.

Pour chaque row en attente (`publisher_id IS NULL` et `publisher_checked_at IS NULL`, RA gérée), interroge `/prefixes` en routant par Registration Agency (`Crossref`/`DataCite` → l'endpoint correspondant ; `unknown` → tente les deux et corrige la RA), renseigne les métadonnées (`publisher_*`, `crossref_member_id`, `client_*`, `datacite_client_symbol`), puis match ou crée le publisher contre `publisher_name_forms` et l'attache. Chaque row est marquée vérifiée (`publisher_checked_at`) : `/prefixes` n'est tenté qu'une fois par row, succès ou échec, ce qui garde contre la réinterrogation sans fin. Placé après `normalize` pour matcher contre les publishers déjà créés par les sources.

La Registration Agency de chaque préfixe est posée en amont par la phase `resolve_ra`. Les clients HTTP (`api.crossref.org/prefixes`, `api.datacite.org/prefixes`) sont injectés en callables, pour la testabilité et l'étanchéité DDD (`application` ne dépend pas d'`infrastructure`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.circuit_breaker import CircuitBreaker
from application.ports.repositories.doi_prefix_repository import (
    DoiPrefixRepository,
    PendingPublisherPrefix,
)
from application.ports.repositories.publisher_repository import PublisherRepository
from domain.normalize import normalize_text

FetchCrossrefPrefixFn = Callable[[str], tuple[str, int | None] | None]
"""Signature : `(prefix) -> (publisher_name, member_id) | None`."""

FetchDataCitePrefixFn = Callable[[str], tuple[str, str, str] | None]
"""Signature : `(prefix) -> (provider_name, client_name, client_symbol) | None`."""


def run_resolve_publishers(
    log: logging.Logger,
    *,
    repo: DoiPrefixRepository,
    publisher_repo: PublisherRepository,
    fetch_crossref_prefix_fn: FetchCrossrefPrefixFn,
    fetch_datacite_prefix_fn: FetchDataCitePrefixFn,
    breaker: CircuitBreaker | None = None,
) -> PhaseMetrics:
    """Détermine et attache le publisher des préfixes en attente via `/prefixes`.

    `total` = préfixes traités ; `extras` = `publisher_matched` / `publisher_created` /
    `no_publisher` (RA gérée mais `/prefixes` muet). S'arrête si le `breaker` a tripé.
    """
    metrics = PhaseMetrics()
    rows = repo.get_prefixes_pending_publisher()
    log.info("resolve_publishers — %d préfixes en attente de publisher", len(rows))

    for row in rows:
        if breaker is not None and breaker.tripped:
            log.warning("resolve_publishers : circuit-breaker tripé, arrêt")
            break
        metrics.add(total=1)
        name_raw = row.publisher_name_raw
        name_normalized = row.publisher_name_normalized
        if name_normalized is None:
            # `/prefixes` pas encore tenté pour cette row → fetch + persistance des métadonnées (et correction de la RA si elle était `unknown`).
            name_raw, name_normalized = _fetch_and_store_publisher_metadata(
                row,
                repo=repo,
                fetch_crossref_prefix_fn=fetch_crossref_prefix_fn,
                fetch_datacite_prefix_fn=fetch_datacite_prefix_fn,
            )

        if name_normalized is not None:
            assert name_raw is not None
            publisher_id, created = publisher_repo.match_or_create_by_name_form(
                name_raw, name_normalized
            )
            repo.update_publisher_id(row.prefix, publisher_id)
            metrics.add(**{"publisher_created" if created else "publisher_matched": 1})
            log.info(
                "  %s → publisher_id=%d (%s)",
                row.prefix,
                publisher_id,
                "créé" if created else "matché",
            )
        else:
            metrics.add(no_publisher=1)
            log.info("  %s → pas de publisher (RA %s, /prefixes muet)", row.prefix, row.ra)

        # Tentative effectuée (succès ou échec) → ne plus reprendre cette row.
        repo.mark_publisher_checked(row.prefix)

    return metrics


def _fetch_and_store_publisher_metadata(
    row: PendingPublisherPrefix,
    *,
    repo: DoiPrefixRepository,
    fetch_crossref_prefix_fn: FetchCrossrefPrefixFn,
    fetch_datacite_prefix_fn: FetchDataCitePrefixFn,
) -> tuple[str | None, str | None]:
    """Interroge `/prefixes` (routé par RA, `unknown` → les deux + correction RA),
    persiste les métadonnées de la row. Retourne `(name_raw, name_normalized)`."""
    ra = row.ra
    crossref_info: tuple[str, int | None] | None = None
    datacite_info: tuple[str, str, str] | None = None
    if ra == "Crossref":
        crossref_info = fetch_crossref_prefix_fn(row.prefix)
    elif ra == "DataCite":
        datacite_info = fetch_datacite_prefix_fn(row.prefix)
    else:  # unknown : tente les deux, corrige la RA selon l'endpoint qui répond
        crossref_info = fetch_crossref_prefix_fn(row.prefix)
        if crossref_info is not None:
            ra = "Crossref"
        else:
            datacite_info = fetch_datacite_prefix_fn(row.prefix)
            if datacite_info is not None:
                ra = "DataCite"

    publisher_name_raw: str | None = None
    publisher_name_normalized: str | None = None
    crossref_member_id: int | None = None
    client_name_raw: str | None = None
    client_name_normalized: str | None = None
    datacite_client_symbol: str | None = None

    if crossref_info is not None:
        publisher_name_raw, crossref_member_id = crossref_info
        publisher_name_normalized = normalize_text(publisher_name_raw) or None
    elif datacite_info is not None:
        publisher_name_raw, client_name_raw, datacite_client_symbol = datacite_info
        publisher_name_normalized = normalize_text(publisher_name_raw) or None
        client_name_normalized = normalize_text(client_name_raw) or None

    # Persiste même si le nom est vide : la row sera marquée vérifiée par l'appelant, donc pas de re-fetch — autant garder la RA corrigée et les colonnes à jour.
    repo.set_prefix_publisher_metadata(
        prefix=row.prefix,
        ra=ra,
        publisher_name_raw=publisher_name_raw,
        publisher_name_normalized=publisher_name_normalized,
        crossref_member_id=crossref_member_id,
        client_name_raw=client_name_raw,
        client_name_normalized=client_name_normalized,
        datacite_client_symbol=datacite_client_symbol,
    )
    return publisher_name_raw, publisher_name_normalized
