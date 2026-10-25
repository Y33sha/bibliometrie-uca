"""Phase `resolve_ra` : résolution préfixe DOI → Registration Agency, après `affiliations` et avant `publishing`.

Soumet à `doi.org/ra` les préfixes valides (`DoiPrefix`) de tous les DOI connus absents de `doi_prefixes`, et insère `(prefix, ra)`. Un préfixe que doi.org ne connaît pas est inséré avec `ra='unknown'`. Un préfixe sans réponse, faute de requête aboutie, reste à résoudre.

La Registration Agency dit laquelle des deux API connaît un DOI, Crossref ou DataCite. La phase `publishing` rattache ensuite les préfixes à leur éditeur via les API `/prefixes`. Au run suivant, `fetch_missing` adresse chaque DOI à la bonne API et laisse attendre ceux dont le préfixe reste à résoudre.

La requête à `doi.org/ra` est injectée par le câblage de la phase.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.publications.identifiers import DoiPrefix
from pipeline.http.circuit_breaker import SourceUnavailableError
from pipeline.http.polite_pool import default_user_agent
from pipeline.ingestion.complements.doi_org import fetch_registration_agencies
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.log_format import (
    LAST_BRANCH,
    inflect,
    nothing_to_do,
    quantity,
    step,
)
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import signal_source_unavailable
from pipeline.task_runner import SingleTaskPhase
from pipeline.transformation.publishing.doi_prefixes import DoiPrefixStore

ResolveRasFn = Callable[[Sequence[str]], Iterable[tuple[str, str | None]]]
"""Signature : `(préfixes) -> (préfixe, agence)` pour chaque préfixe auquel doi.org a répondu. Agence `None` : doi.org ne connaît pas le préfixe."""


@dataclass(frozen=True)
class ResolveRaPhase:
    """`prefix_store_factory` construit les requêtes sur les préfixes sur la connexion de la phase."""

    prefix_store_factory: Callable[[Connection], DoiPrefixStore]
    resolve_ras_fn: ResolveRasFn

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Résout les préfixes dans une transaction.

        Une indisponibilité de doi.org donne des métriques vides, signalées : la transaction commit les préfixes insérés avant l'indisponibilité.
        """
        with ctx.open_tx() as conn:
            try:
                return _resolve(ctx.logger, self.prefix_store_factory(conn), self.resolve_ras_fn)
            except SourceUnavailableError:
                metrics = PhaseMetrics()
                signal_source_unavailable(
                    metrics, "doi.org/ra", logger=ctx.logger, phase="resolve_ra"
                )
                return metrics


def _resolve(
    log: logging.Logger, prefix_store: DoiPrefixStore, resolve_ras_fn: ResolveRasFn
) -> PhaseMetrics:
    """Résout l'agence des préfixes absents de `doi_prefixes` (`doi.org/ra`) et l'insère.

    `total` = préfixes auxquels doi.org a répondu ; `new` = rows insérées ; `extras` = `resolved` / `unresolved`.
    """
    metrics = PhaseMetrics()
    # Un préfixe hors de la forme `10.<chiffres>` vient d'une valeur qui n'est pas un DOI : il n'est pas enregistré.
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

    # Indicateurs sur-mesure : synthèse du run + tableau par Registration Agency (Crossref / DataCite / unknown) avec DOI candidats et préfixes. La part `unknown` inclut les préfixes que doi.org ne connaît pas et les préfixes malformés (DOI à scheme « doi: » non nettoyé).
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


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:

    # doi.org/ra est une API publique : l'adresse du polite pool y est facultative.
    user_agent = default_user_agent()
    return SingleTaskPhase(
        "resolve_ra.resolve_prefixes",
        ResolveRaPhase(
            DoiPrefixStore,
            lambda prefixes: fetch_registration_agencies(prefixes, user_agent=user_agent),
        ),
        label="Bilan",
    )
