"""Résolution préfixe DOI → Registration Agency + éditeur/repository.

Scindée en deux fonctions, appelées par deux phases distinctes :

**`run_resolve_ra`** (phase `resolve_ra`, avant `cross_imports`). Pour chaque préfixe du pool `candidate_dois` absent de `doi_prefixes` : récupère quelques DOI samples, interroge `doi.org/ra` (premier sample qui répond), insère `(prefix, ra)`. Préfixe que doi.org/ra ne classe pas → inséré avec `ra='unknown'` (le volet publisher tentera `/prefixes` pour le rattraper). Aucun appel `/prefixes`, aucun publisher ici — c'est tout ce dont `cross_imports` a besoin pour router les fetches par RA.

**`run_resolve_publishers`** (phase `publishers_journals`, après `normalize`). Pour chaque row en attente (`publisher_id IS NULL` et `publisher_checked_at IS NULL`, RA gérée) : interroge `/prefixes` en routant par RA (`Crossref`/`DataCite` → l'endpoint correspondant ; `unknown` → tente les deux et corrige la RA), renseigne les métadonnées (`publisher_*`, `crossref_member_id`, `client_*`, `datacite_client_symbol`), puis match/crée le publisher contre `publisher_name_forms` et l'attache. Chaque row est marquée vérifiée (`publisher_checked_at`) → `/prefixes` tenté une seule fois par row, succès ou échec (garde contre la réinterrogation sans fin). Placée après `normalize` pour matcher contre les publishers déjà créés par les sources.

Les clients HTTP (doi.org/ra, api.crossref.org/prefixes, api.datacite.org/prefixes) sont injectés en callables pour testabilité et étanchéité DDD (application ne dépend pas d'infrastructure).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.circuit_breaker import CircuitBreaker
from application.ports.repositories.doi_prefix_repository import (
    DoiPrefixRepository,
    PendingPublisherPrefix,
)
from application.ports.repositories.publisher_repository import PublisherRepository
from domain.normalize import normalize_text

ResolveRaFn = Callable[[str], str | None]
"""Signature : `(doi) -> ra_name | None`. `None` = DOI inexistant ou erreur HTTP."""

FetchCrossrefPrefixFn = Callable[[str], tuple[str, int | None] | None]
"""Signature : `(prefix) -> (publisher_name, member_id) | None`."""

FetchDataCitePrefixFn = Callable[[str], tuple[str, str, str] | None]
"""Signature : `(prefix) -> (provider_name, client_name, client_symbol) | None`."""


def run_resolve_ra(
    log: logging.Logger,
    *,
    repo: DoiPrefixRepository,
    resolve_ra_fn: ResolveRaFn,
    n_samples: int = 3,
    dry_run: bool = False,
    limit: int | None = None,
    breaker: CircuitBreaker | None = None,
) -> PhaseMetrics:
    """Résout la RA des préfixes non encore en base (`doi.org/ra` seul) et l'insère.

    `total` = préfixes traités ; `new` = rows insérées ; `extras` = `resolved` / `unresolved`.
    S'arrête si le `breaker` a tripé (doi.org à bout de budget).
    """
    log.info("▶ resolve_ra")
    t0 = time.perf_counter()
    metrics = PhaseMetrics()
    prefixes = repo.get_unresolved_prefixes_with_samples(n_samples_per_prefix=n_samples)
    log.info("%d préfixes à résoudre", len(prefixes))

    if limit is not None:
        prefixes = prefixes[:limit]
        log.info("Limité à %d préfixes", len(prefixes))

    if dry_run:
        log.info("Dry-run — aucun appel doi.org/ra, aucun insert")
        metrics.add(total=len(prefixes))
        return metrics

    new_by_ra: dict[str, int] = {}
    for prefix, samples in prefixes:
        if breaker is not None and breaker.tripped:
            log.warning("circuit-breaker tripé, arrêt (doi.org indisponible)")
            break
        metrics.add(total=1)
        ra = _resolve_ra_with_retry(prefix, samples, resolve_ra_fn, log)
        if ra is None:
            ra = "unknown"
            metrics.add(unresolved=1)
        else:
            metrics.add(resolved=1)
        if repo.insert_ra(prefix=prefix, ra=ra):
            metrics.add(new=1)
            new_by_ra[ra] = new_by_ra.get(ra, 0) + 1
        log.info("%s → %s", prefix, ra)

    # Indicateurs sur-mesure : synthèse du run + tableau par Registration Agency
    # (Crossref / DataCite / unknown) avec DOI candidats et préfixes. La part `unknown`
    # inclut les préfixes que doi.org/ra ne classe pas et les préfixes malformés (DOI à
    # scheme « doi: » non nettoyé), ce qui la rend lisible comme signal de qualité.
    metrics.details["summary"] = {
        "new_prefixes": metrics.new,
        "resolved": metrics.extras.get("resolved", 0),
    }
    metrics.details["table"] = {
        "rows": [
            {"key": ra, "dois": dois, "prefixes": n_prefixes, "new": new_by_ra.get(ra, 0)}
            for ra, dois, n_prefixes in repo.breakdown_by_registration_agency()
        ]
    }
    log.info("✓ resolve_ra terminé en %.1fs — %s", time.perf_counter() - t0, metrics.as_summary())
    return metrics


def run_resolve_publishers(
    log: logging.Logger,
    *,
    repo: DoiPrefixRepository,
    publisher_repo: PublisherRepository,
    fetch_crossref_prefix_fn: FetchCrossrefPrefixFn,
    fetch_datacite_prefix_fn: FetchDataCitePrefixFn,
    dry_run: bool = False,
    breaker: CircuitBreaker | None = None,
) -> PhaseMetrics:
    """Détermine et attache le publisher des préfixes en attente via `/prefixes`.

    `total` = préfixes traités ; `extras` = `publisher_matched` / `publisher_created` /
    `no_publisher` (RA gérée mais `/prefixes` muet). S'arrête si le `breaker` a tripé.
    """
    metrics = PhaseMetrics()
    rows = repo.get_prefixes_pending_publisher()
    log.info("resolve_publishers — %d préfixes en attente de publisher", len(rows))

    if dry_run:
        log.info("Dry-run — aucun appel /prefixes, aucun UPDATE")
        metrics.add(total=len(rows))
        return metrics

    for row in rows:
        if breaker is not None and breaker.tripped:
            log.warning("resolve_publishers : circuit-breaker tripé, arrêt")
            break
        metrics.add(total=1)
        name_raw = row.publisher_name_raw
        name_normalized = row.publisher_name_normalized
        if name_normalized is None:
            # `/prefixes` pas encore tenté pour cette row → fetch + persistance des
            # métadonnées (et correction de la RA si elle était `unknown`).
            name_raw, name_normalized = _fetch_and_store_publisher_metadata(
                row,
                repo=repo,
                fetch_crossref_prefix_fn=fetch_crossref_prefix_fn,
                fetch_datacite_prefix_fn=fetch_datacite_prefix_fn,
            )

        if name_normalized is not None:
            assert name_raw is not None
            publisher_id, created = _match_or_create_publisher(
                publisher_repo, name_raw=name_raw, name_normalized=name_normalized
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

    # Persiste même si le nom est vide : la row sera marquée vérifiée par l'appelant,
    # donc pas de re-fetch — autant garder la RA corrigée et les colonnes à jour.
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


def _match_or_create_publisher(
    publisher_repo: PublisherRepository,
    *,
    name_raw: str,
    name_normalized: str,
) -> tuple[int, bool]:
    """Cherche un publisher par forme normalisée ; crée-le si absent.

    Retourne `(publisher_id, created)`. La création insère également la
    forme normalisée dans `publisher_name_forms`, ce qui permet aux appels
    suivants dans la même transaction (et au-delà) de retomber dessus via
    `find_publisher_by_name_form` — dédoublonnage naturel sans cache local.
    """
    existing = publisher_repo.find_publisher_by_name_form(name_normalized)
    if existing is not None:
        return existing, False
    new_id = publisher_repo.create_publisher(
        name=name_raw, name_normalized=name_normalized, openalex_id=None
    )
    publisher_repo.add_publisher_name_form(new_id, name_normalized)
    return new_id, True


def _resolve_ra_with_retry(
    prefix: str,
    samples: list[str],
    resolve_ra_fn: ResolveRaFn,
    log: logging.Logger,
) -> str | None:
    """Tente chaque DOI sample jusqu'à obtenir une RA valide. Renvoie None si tous
    les samples échouent (le préfixe sera marqué `unknown`, repris par le volet publisher)."""
    for doi in samples:
        ra = resolve_ra_fn(doi)
        if ra is not None:
            return ra
        log.debug("%s : sample %s non résoluble, tente le suivant", prefix, doi)
    log.warning("%s : tous les samples ont échoué (%d) → unknown", prefix, len(samples))
    return None
