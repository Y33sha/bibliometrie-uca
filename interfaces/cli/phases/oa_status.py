"""Câblage de la phase `oa_status`."""

from __future__ import annotations

from interfaces.cli.phases.execution import UnderCircuitBreaker, credentials_missing
from pipeline.context import Phase


def build() -> Phase:
    """Enrichissement de `publications.oa_status`, une publication à la fois, via Unpaywall.

    Le délai de péremption et le plafond par run bornent la phase : le retard des publications jamais vérifiées s'écoule d'un run à l'autre. Unpaywall exige l'adresse électronique du polite pool ; sans elle, la phase est sautée. La phase tourne sous le circuit-breaker d'Unpaywall.

    Séquence et métriques dans `pipeline/publications/oa_status.py` ; ici, le câblage : circuit-breaker, client Unpaywall.
    """
    import httpx2

    from application.ports.pipeline.lookup import LookupOutcome
    from infrastructure.sources.api_params import API_BASE_URLS
    from infrastructure.sources.config import (
        get_polite_pool_email_optional,
        get_unpaywall_max_per_run,
        get_unpaywall_recheck_after_days,
    )
    from pipeline.publications.oa_status import OaStatusPhase
    from pipeline.publications.oa_status_queries import OaStatusQueries
    from pipeline.sources.unpaywall import fetch_oa_status

    base_url = API_BASE_URLS["unpaywall"]
    email = get_polite_pool_email_optional() or ""

    async def fetcher(client: httpx2.AsyncClient, doi: str) -> LookupOutcome[str]:
        return await fetch_oa_status(client, doi, base_url=base_url, email=email)

    return UnderCircuitBreaker(
        "unpaywall",
        OaStatusPhase(
            OaStatusQueries(),
            fetcher,
            credentials_missing=credentials_missing,
            staleness_days=get_unpaywall_recheck_after_days,
            max_per_run=get_unpaywall_max_per_run,
        ),
    )
