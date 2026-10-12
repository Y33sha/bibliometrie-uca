"""Câblage de la phase `resolve_ra`."""

from __future__ import annotations

from interfaces.cli.phases.execution import UnderCircuitBreaker
from pipeline.context import Phase


def build() -> Phase:
    """Résout la Registration Agency des préfixes de tous les DOI connus (`doi.org/ra`), après la normalisation du run.

    La Registration Agency dit laquelle des deux API connaît un DOI, Crossref ou DataCite. La phase `publishers_journals`, qui suit, rattache les préfixes à leur éditeur via les API `/prefixes` ; `fetch_missing`, au run suivant, adresse chaque DOI à la bonne API et laisse attendre ceux dont le préfixe n'est pas encore résolu.

    Séquence, transaction et métriques dans `pipeline/containers/resolve_ra.py` ; ici, le câblage : circuit-breaker, user-agent.
    """
    from infrastructure.sources.config import get_polite_pool_email_optional
    from infrastructure.sources.polite_pool import build_user_agent
    from pipeline.containers.doi_prefixes import DoiPrefixesQueries
    from pipeline.containers.resolve_ra import ResolveRaPhase
    from pipeline.sources.doi_org import fetch_registration_agencies

    # doi.org/ra est une API publique : l'adresse du polite pool y est facultative.
    user_agent = build_user_agent(get_polite_pool_email_optional() or "")
    return UnderCircuitBreaker(
        "doi.org/ra",
        ResolveRaPhase(
            DoiPrefixesQueries,
            lambda prefixes: fetch_registration_agencies(prefixes, user_agent=user_agent),
        ),
    )
