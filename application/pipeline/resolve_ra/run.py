"""Phase `resolve_ra` : résolution préfixe DOI → Registration Agency, avant `cross_imports`.

Pour chaque préfixe du pool `candidate_dois` absent de `doi_prefixes`, récupère quelques DOI samples, interroge `doi.org/ra` (le premier sample qui répond) et insère `(prefix, ra)`. Un préfixe que `doi.org/ra` ne classe pas est inséré avec `ra='unknown'` : le volet publisher de `publishers_journals` tentera `/prefixes` pour le rattraper. Aucun appel `/prefixes`, aucun publisher ici — c'est tout ce dont `cross_imports` a besoin pour router les fetches par Registration Agency.

Le client HTTP (`doi.org/ra`) est injecté en callable, pour la testabilité et l'étanchéité DDD (`application` ne dépend pas d'`infrastructure`).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.circuit_breaker import CircuitBreaker
from application.ports.repositories.doi_prefix_repository import DoiPrefixRepository

ResolveRaFn = Callable[[str], str | None]
"""Signature : `(doi) -> ra_name | None`. `None` = DOI inexistant ou erreur HTTP."""


def run_resolve_ra(
    log: logging.Logger,
    *,
    repo: DoiPrefixRepository,
    resolve_ra_fn: ResolveRaFn,
    n_samples: int = 3,
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
