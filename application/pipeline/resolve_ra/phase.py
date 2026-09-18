"""Phase `resolve_ra` : résolution préfixe DOI → Registration Agency, avant `fetch_missing`.

Soumet à `doi.org/ra` les préfixes valides (`DoiPrefix`) du pool `candidate_dois` absents de `doi_prefixes`, et insère `(prefix, ra)`. Un préfixe que doi.org ne connaît pas est inséré avec `ra='unknown'`. Un préfixe sans réponse, faute de requête aboutie, reste à résoudre.

Le client HTTP (`doi.org/ra`) est injecté en callable, pour la testabilité et l'étanchéité DDD (`application` ne dépend pas d'`infrastructure`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence

from application.pipeline.libelles import accord, forme
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.doi_prefixes import DoiPrefixesQueries
from domain.publications.identifiers import DoiPrefix

ResolveRasFn = Callable[[Sequence[str]], Iterable[tuple[str, str | None]]]
"""Signature : `(préfixes) -> (préfixe, agence)` pour chaque préfixe auquel doi.org a répondu. Agence `None` : doi.org ne connaît pas le préfixe."""


def run(
    log: logging.Logger,
    *,
    repo: DoiPrefixesQueries,
    resolve_ras_fn: ResolveRasFn,
) -> PhaseMetrics:
    """Résout l'agence des préfixes absents de `doi_prefixes` (`doi.org/ra`) et l'insère.

    `total` = préfixes auxquels doi.org a répondu ; `new` = rows insérées ; `extras` = `resolved` / `unresolved`.
    """
    metrics = PhaseMetrics()
    # Un préfixe hors de la forme `10.<chiffres>` vient d'une valeur qui n'est pas un DOI : il n'est pas enregistré.
    prefixes = [
        prefix
        for prefix in repo.get_prefixes_to_resolve()
        if str(DoiPrefix.try_parse(prefix)) == prefix
    ]
    log.info("%s à résoudre", accord(len(prefixes), "préfixe DOI", "préfixes DOI"))
    if prefixes:
        log.info("")

    new_by_ra: dict[str, int] = {}
    for prefix, answer in resolve_ras_fn(prefixes):
        ra = answer or "unknown"
        metrics.add(total=1, **{"resolved" if answer else "unresolved": 1})
        if repo.insert_ra(prefix=prefix, ra=ra):
            metrics.add(new=1)
            new_by_ra[ra] = new_by_ra.get(ra, 0) + 1
        log.info("%s → %s", prefix, ra)

    # Indicateurs sur-mesure : synthèse du run + tableau par Registration Agency (Crossref / DataCite / unknown) avec DOI candidats et préfixes. La part `unknown` inclut les préfixes que doi.org ne connaît pas et les préfixes malformés (DOI à scheme « doi: » non nettoyé).
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
    resolus = metrics.extras.get("resolved", 0)
    total = metrics.total
    metrics.resume = f"{resolus}/{total} {forme(total, 'préfixe')} {forme(total, 'résolu')}"
    return metrics
