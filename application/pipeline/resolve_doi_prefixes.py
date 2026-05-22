"""Phase pipeline : résolution préfixe DOI → Registration Agency + éditeur.

Deux passes :

**Passe 1 — nouveaux préfixes du staging.** Pour chaque préfixe DOI
présent en staging mais absent de `doi_prefixes` :

1. Récupère jusqu'à `n_samples` DOI samples du staging pour ce préfixe.
2. Interroge `doi.org/ra` dans l'ordre via `resolve_ra_fn`. Premier
   sample qui renvoie une RA valide → on garde la valeur. Si tous les
   samples échouent (DOI inexistant, erreur réseau), **on n'insère
   pas** le préfixe : retry au prochain run.
3. Si RA = `'Crossref'`, interroge `api.crossref.org/prefixes/<prefix>`
   via `fetch_crossref_prefix_fn` pour récupérer `(name, member_id)`.
   Normalise le nom via `normalize_text`, matche contre
   `publisher_name_forms` pour rattacher un `publisher_id` existant.
   **Si aucun match, crée le publisher** (+ son `publisher_name_form`)
   plutôt que de laisser `publisher_id NULL`. Évite les préfixes
   orphelins ; les doublons éventuels avec des publishers issus des
   sources sont rattrapés via fusion manuelle côté admin.
4. Insère la row `doi_prefixes`.

**Passe 2 — rattrapage des rows existantes.** Pour chaque row
`doi_prefixes` connue de Crossref (`publisher_name_normalized` rempli)
mais sans `publisher_id` :

1. Retente le match contre `publisher_name_forms` (un nouveau publisher
   a peut-être été créé entre-temps).
2. Si toujours pas de match, crée le publisher.
3. `UPDATE doi_prefixes SET publisher_id = ...`.

Placée **après normalize** dans le pipeline : (a) `cross_imports` (en
amont) peut introduire de nouveaux DOIs via `fetch_missing_hal_id` qu'il
faut prendre en compte ; (b) `normalize` crée les `publishers` (via
`find_or_create_publisher`), donc matcher après normalize permet un vrai
match plutôt qu'un best-effort qui laisserait `publisher_id NULL`.

Les clients HTTP (doi.org/ra, api.crossref.org/prefixes) sont injectés
en tant que callables pour testabilité et étanchéité DDD (application
ne dépend pas d'infrastructure).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from application.pipeline.metrics import PhaseMetrics
from application.ports.repositories.doi_prefix_repository import DoiPrefixRepository
from application.ports.repositories.publisher_repository import PublisherRepository
from domain.normalize import normalize_text

ResolveRaFn = Callable[[str], str | None]
"""Signature : `(doi) -> ra_name | None`. `None` = DOI inexistant ou erreur HTTP."""

FetchCrossrefPrefixFn = Callable[[str], tuple[str, int | None] | None]
"""Signature : `(prefix) -> (publisher_name, member_id) | None`."""


def run_resolve_doi_prefixes(
    log: logging.Logger,
    *,
    repo: DoiPrefixRepository,
    publisher_repo: PublisherRepository,
    resolve_ra_fn: ResolveRaFn,
    fetch_crossref_prefix_fn: FetchCrossrefPrefixFn,
    n_samples: int = 3,
    dry_run: bool = False,
    limit: int | None = None,
) -> PhaseMetrics:
    """Résout les préfixes DOI inconnus en staging + rattrape les rows existantes.

    Args:
        log: logger.
        repo: port `DoiPrefixRepository`.
        publisher_repo: port `PublisherRepository` (match + création).
        resolve_ra_fn: callable interrogeant doi.org/ra.
        fetch_crossref_prefix_fn: callable interrogeant
            api.crossref.org/prefixes (uniquement pour RA=Crossref).
        n_samples: nombre max de DOI samples tentés par préfixe.
        dry_run: si True, log le plan sans rien insérer.
        limit: nombre max de préfixes à traiter en passe 1 (passe 2 non
            limitée — peu coûteuse, pas d'appel API).

    Returns:
        `PhaseMetrics` : `total` = préfixes traités (passes 1+2), `new` =
        rows `doi_prefixes` insérées (passe 1), `extras` = compteurs
        détaillés (`resolved`, `unresolved`, `crossref_matched`,
        `crossref_created`, `retried` pour la passe 2).
    """
    metrics = PhaseMetrics()
    metrics.merge(
        _pass_new_prefixes(
            log,
            repo=repo,
            publisher_repo=publisher_repo,
            resolve_ra_fn=resolve_ra_fn,
            fetch_crossref_prefix_fn=fetch_crossref_prefix_fn,
            n_samples=n_samples,
            dry_run=dry_run,
            limit=limit,
        )
    )
    metrics.merge(
        _pass_retry_unmatched(
            log,
            repo=repo,
            publisher_repo=publisher_repo,
            dry_run=dry_run,
        )
    )
    log.info(
        "Terminé : %d préfixes traités au total (%s)",
        metrics.total,
        metrics.as_summary(),
    )
    return metrics


def _pass_new_prefixes(
    log: logging.Logger,
    *,
    repo: DoiPrefixRepository,
    publisher_repo: PublisherRepository,
    resolve_ra_fn: ResolveRaFn,
    fetch_crossref_prefix_fn: FetchCrossrefPrefixFn,
    n_samples: int,
    dry_run: bool,
    limit: int | None,
) -> PhaseMetrics:
    """Passe 1 : résout les nouveaux préfixes du staging."""
    metrics = PhaseMetrics()
    prefixes = repo.get_unresolved_prefixes_with_samples(n_samples_per_prefix=n_samples)
    log.info("Passe 1 — %d préfixes à résoudre (staging)", len(prefixes))

    if limit is not None:
        prefixes = prefixes[:limit]
        log.info("Limité à %d préfixes", len(prefixes))

    if dry_run:
        log.info("Dry-run — aucun appel API, aucun insert")
        metrics.add(total=len(prefixes))
        return metrics

    for prefix, samples in prefixes:
        metrics.add(total=1)
        ra = _resolve_ra_with_retry(prefix, samples, resolve_ra_fn, log)
        if ra is None:
            metrics.add(unresolved=1)
            continue
        metrics.add(resolved=1)

        publisher_id: int | None = None
        publisher_name_raw: str | None = None
        publisher_name_normalized: str | None = None
        crossref_member_id: int | None = None

        if ra == "Crossref":
            crossref_info = fetch_crossref_prefix_fn(prefix)
            if crossref_info is not None:
                publisher_name_raw, crossref_member_id = crossref_info
                publisher_name_normalized = normalize_text(publisher_name_raw) or None
                if publisher_name_normalized:
                    publisher_id, created = _match_or_create_publisher(
                        publisher_repo,
                        name_raw=publisher_name_raw,
                        name_normalized=publisher_name_normalized,
                    )
                    metrics.add(**{"crossref_created" if created else "crossref_matched": 1})

        inserted = repo.insert_doi_prefix(
            prefix=prefix,
            ra=ra,
            publisher_id=publisher_id,
            publisher_name_raw=publisher_name_raw,
            publisher_name_normalized=publisher_name_normalized,
            crossref_member_id=crossref_member_id,
        )
        if inserted:
            metrics.add(new=1)
        log.info(
            "  %s → %s%s%s",
            prefix,
            ra,
            f" / publisher_id={publisher_id}" if publisher_id else "",
            f" / member={crossref_member_id}" if crossref_member_id else "",
        )

    return metrics


def _pass_retry_unmatched(
    log: logging.Logger,
    *,
    repo: DoiPrefixRepository,
    publisher_repo: PublisherRepository,
    dry_run: bool,
) -> PhaseMetrics:
    """Passe 2 : rattrape les rows `doi_prefixes` Crossref-connues sans publisher_id."""
    metrics = PhaseMetrics()
    rows = repo.get_unmatched_crossref_prefixes()
    log.info("Passe 2 — %d préfixes Crossref-connus sans publisher à rattraper", len(rows))

    if dry_run:
        log.info("Dry-run — pas d'UPDATE")
        metrics.add(total=len(rows), retried=len(rows))
        return metrics

    for row in rows:
        metrics.add(total=1, retried=1)
        publisher_id, created = _match_or_create_publisher(
            publisher_repo,
            name_raw=row.publisher_name_raw,
            name_normalized=row.publisher_name_normalized,
        )
        repo.update_publisher_id(row.prefix, publisher_id)
        metrics.add(**{"crossref_created" if created else "crossref_matched": 1})
        log.info(
            "  %s → publisher_id=%d (%s)",
            row.prefix,
            publisher_id,
            "créé" if created else "matché",
        )

    return metrics


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
    """Tente chaque DOI sample jusqu'à obtenir une RA valide. Renvoie
    None si tous les samples échouent."""
    for doi in samples:
        ra = resolve_ra_fn(doi)
        if ra is not None:
            return ra
        log.debug("  %s : sample %s non résoluble, tente le suivant", prefix, doi)
    log.warning("  %s : tous les samples ont échoué (%d), pas d'insert", prefix, len(samples))
    return None
