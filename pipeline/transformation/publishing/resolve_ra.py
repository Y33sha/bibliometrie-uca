"""Phase `resolve_ra` : résolution préfixe DOI → Registration Agency.

Soumet à `doi.org/ra` les préfixes valides (`DoiPrefix`) de tous les DOI connus absents de `doi_prefixes`, et insère `(prefix, ra)`. Un préfixe inconnu de doi.org est inséré avec `ra='unknown'`. Un préfixe sans réponse, faute de requête aboutie, reste à résoudre.

La Registration Agency désigne l'API où chercher un DOI, Crossref ou DataCite. La phase `publishing` rattache ensuite les préfixes à leur éditeur via les API `/prefixes`. Au run suivant, `fetch_missing` adresse chaque DOI à la bonne API et met en attente les DOI à préfixe non résolu.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence

from domain.documents.identifiers import DoiPrefix
from domain.sources.registry import DOI_ORG
from pipeline.graph import Task
from pipeline.http.circuit_breaker import SourceUnavailableError, trip_source
from pipeline.http.polite_pool import default_user_agent
from pipeline.ingestion.complements.doi_org import fetch_registration_agencies
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import (
    LAST_BRANCH,
    inflect,
    nothing_to_do,
    quantity,
    step,
)
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.doi_prefixes import DoiPrefixStore

ResolveRasFn = Callable[[Sequence[str]], Iterable[tuple[str, str | None]]]
"""Signature : `(préfixes) -> (préfixe, agence)` pour chaque préfixe auquel doi.org a répondu. Agence `None` : préfixe inconnu de doi.org."""


def resolve_prefixes(ctx: PhaseContext) -> PhaseMetrics:
    """Résout l'agence des préfixes absents de `doi_prefixes` auprès de doi.org, dans une transaction."""
    # doi.org/ra est une API publique : l'adresse du polite pool y est facultative.
    user_agent = default_user_agent()
    with ctx.open_tx() as conn:
        return resolve(
            ctx.logger,
            DoiPrefixStore(conn),
            lambda prefixes: fetch_registration_agencies(prefixes, user_agent=user_agent),
        )


def resolve(
    log: logging.Logger, prefix_store: DoiPrefixStore, resolve_ras_fn: ResolveRasFn
) -> PhaseMetrics:
    """Résout l'agence des préfixes absents de `doi_prefixes` par `resolve_ras_fn`, et l'insère.

    Une indisponibilité de doi.org coupe la source et arrête la résolution. Les préfixes insérés avant restent dans la transaction, et les métriques les comptent.

    Returns:
        Métriques : `total`, préfixes auxquels doi.org a répondu ; `new`, lignes insérées ; `extras`, `resolved` / `unresolved`.
    """
    metrics = PhaseMetrics()
    # Seuls les préfixes de forme `10.<chiffres>` sont soumis. Les autres proviennent de valeurs autres que des DOI.
    prefixes = [
        prefix
        for prefix in prefix_store.get_prefixes_to_resolve()
        if str(DoiPrefix.try_parse(prefix)) == prefix
    ]
    step(log, "Agences d'enregistrement des préfixes DOI")
    if not prefixes:
        nothing_to_do(log)
    else:
        log.info(
            "%s%s à résoudre",
            LAST_BRANCH,
            quantity(len(prefixes), "préfixe DOI", "préfixes DOI"),
        )

    new_by_ra: dict[str, int] = {}
    try:
        for prefix, answer in resolve_ras_fn(prefixes):
            ra = answer or "unknown"
            if answer:
                metrics.add(seen=1, resolved=1)
            else:
                metrics.add(seen=1, unresolved=1)
            if prefix_store.insert_ra(prefix=prefix, ra=ra):
                metrics.add(new=1)
                new_by_ra[ra] = new_by_ra.get(ra, 0) + 1
            log.info("     %s → %s", prefix, ra)
    except SourceUnavailableError:
        trip_source()

    # Synthèse du run et tableau des DOI candidats et des préfixes par Registration Agency (Crossref, DataCite, unknown).
    metrics.details["summary"] = {
        "new_prefixes": metrics.new,
        "resolved": metrics.extras.get("resolved", 0),
    }
    metrics.details["table"] = {
        "rows": [
            {"key": ra, "dois": dois, "prefixes": n_prefixes, "new": new_by_ra.get(ra, 0)}
            for ra, dois, n_prefixes in prefix_store.breakdown_by_registration_agency()
        ]
    }
    resolved = metrics.extras.get("resolved", 0)
    total = metrics.total
    metrics.report = f"{resolved}/{total} {inflect(total, 'préfixe')} {inflect(total, 'résolu')}"
    return metrics


TASKS = (
    Task(
        "resolve_prefixes",
        reads=(
            "doi_prefixes.id",
            "source_record_identifiers",
            "publication_relations",
        ),
        writes=("doi_prefixes.id", "doi_prefixes.ra"),
        previous_run=("source_records", "source_record_identifiers", "publication_relations"),
        network=DOI_ORG,
        run=resolve_prefixes,
        label="Bilan",
    ),
)
