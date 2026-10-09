"""Câblage de la phase `oa_status`."""

from __future__ import annotations

from application.pipeline.context import Phase
from interfaces.cli.phases.execution import credentials_missing, log


def build() -> Phase:
    """Enrichissement de `publications.oa_status`, une publication à la fois, via Unpaywall.

    Le délai de péremption et le plafond par run bornent la phase : le retard des publications jamais vérifiées s'écoule d'un run à l'autre. Unpaywall exige l'adresse électronique du polite pool ; sans elle, la phase est sautée.

    Séquence et métriques dans `application/pipeline/oa_status/phase.py` ; ici, le câblage.
    """
    import httpx2

    from application.pipeline.oa_status.phase import OaStatusPhase
    from infrastructure.pipeline.oa_status import PgOaStatusQueries
    from infrastructure.sources.api_params import API_BASE_URLS
    from infrastructure.sources.config import (
        get_polite_pool_email_optional,
        get_unpaywall_max_per_run,
        get_unpaywall_recheck_after_days,
    )
    from infrastructure.sources.unpaywall.client import fetch_oa_status

    base_url = API_BASE_URLS["unpaywall"]
    email = get_polite_pool_email_optional() or ""

    async def fetcher(client: httpx2.AsyncClient, doi: str) -> str | None:
        return await fetch_oa_status(client, doi, base_url=base_url, email=email, logger=log)

    return OaStatusPhase(
        PgOaStatusQueries(),
        fetcher,
        credentials_missing=credentials_missing,
        staleness_days=get_unpaywall_recheck_after_days,
        max_per_run=get_unpaywall_max_per_run,
    )
