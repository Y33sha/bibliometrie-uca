"""Câblage de la phase `resolve_ra`."""

from __future__ import annotations

from dataclasses import dataclass

from application.pipeline.context import Phase, PhaseContext
from application.pipeline.metrics import PhaseMetrics
from interfaces.cli.phases.execution import circuit_breaker, signal_if_tripped


def build() -> Phase:
    """Résout la Registration Agency des préfixes DOI (`doi.org/ra`) avant `fetch_missing`.

    La Registration Agency dit laquelle des deux API connaît un DOI, Crossref ou DataCite : `fetch_missing` adresse ensuite chaque DOI à la bonne. La phase `publishers_journals` reprend les préfixes restants via les API `/prefixes`.

    Séquence, transaction et métriques dans `application/pipeline/resolve_ra/phase.py` ; ici, le câblage : circuit-breaker, user-agent.
    """
    from application.pipeline.resolve_ra.phase import ResolveRaPhase
    from infrastructure.pipeline.doi_prefixes import PgDoiPrefixesQueries
    from infrastructure.sources.config import get_polite_pool_email_optional
    from infrastructure.sources.doi_org.registration_agency import fetch_registration_agencies
    from infrastructure.sources.polite_pool import build_user_agent

    # doi.org/ra est une API publique : l'adresse du polite pool y est facultative.
    user_agent = build_user_agent(get_polite_pool_email_optional() or "")
    return _UnderDoiOrgBreaker(
        ResolveRaPhase(
            PgDoiPrefixesQueries,
            lambda prefixes: fetch_registration_agencies(prefixes, user_agent=user_agent),
        )
    )


@dataclass(frozen=True)
class _UnderDoiOrgBreaker:
    """Exécute la phase sous le circuit-breaker de `doi.org/ra`."""

    phase: Phase

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        with circuit_breaker("doi.org/ra") as breaker:
            metrics = self.phase.run(ctx)
        signal_if_tripped(metrics, breaker)
        return metrics
