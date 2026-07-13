"""Client API ROR (Research Organization Registry) — v2.

Endpoint unique : `GET /v2/organizations/{ror}`, qui retourne le record ROR complet. ROR n'expose pas de bulk endpoint par liste d'IDs — chaque ROR doit être fetché individuellement.

Consommateurs : `application.services.publishers.enrichment.from_ror` (maintenance) + oneshot `audit_ror_types_for_publishers`.

URL de base via `_API_BASE_URLS["ror"]` (cf. `infrastructure.sources.config`).
"""

import logging
from typing import Any

import requests


def fetch_ror_record(
    ror: str,
    *,
    base_url: str,
    user_agent: str,
    logger: logging.Logger,
    timeout: float = 15.0,
) -> dict[str, Any] | None:
    """GET sur l'API ROR v2 pour un ROR ID donné.

    Retourne le record JSON ou `None` sur 404 / erreur réseau. Pas de retry élaboré — les consommateurs sont tolérants à un fetch occasionnellement raté (skip la ligne et continue).
    """
    try:
        resp = requests.get(
            f"{base_url}/{ror}",
            headers={"User-Agent": user_agent},
            timeout=timeout,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.warning("ROR fetch failed for %s : %s", ror, e)
        return None


def build_ror_user_agent(mailto: str) -> str:
    """User-Agent courtois pour les requêtes ROR (contact email)."""
    return f"bibliometrie-uca/1.0 (mailto:{mailto})"
