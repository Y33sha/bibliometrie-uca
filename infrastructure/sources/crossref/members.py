"""Client API Crossref Members — `GET /members/{id}`.

Consommé par le sub-step pipeline `enrich_publishers_from_crossref_members`
(fallback `country` quand OpenAlex Publishers n'a pas eu de match) et
par l'audit `audit_crossref_member_countries`.

Polite pool via header `User-Agent` (mailto), cohérent avec les autres
clients Crossref du projet (`doi_prefixes/clients.py`,
`crossref/fetch_missing_doi.py`).
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from infrastructure.sources.circuit_breaker import SourceCircuitBreaker

CROSSREF_MEMBER_URL = "https://api.crossref.org/members/{id}"


def fetch_crossref_member(
    member_id: int,
    *,
    user_agent: str,
    logger: logging.Logger,
    timeout: float = 15.0,
    breaker: SourceCircuitBreaker | None = None,
) -> dict[str, Any] | None:
    """GET sur `api.crossref.org/members/{id}`.

    Retourne le bloc `message` (= record du member) ou ``None`` sur 404
    / erreur réseau. Pas de retry élaboré ; les consommateurs tolèrent
    un fetch raté.

    Coupe-circuit (budget Crossref) : si `breaker` est fourni et **tripé**,
    on ne tape plus l'API (retourne `None` immédiatement). Un 429 ou une
    panne (5xx / réseau) compte un échec ; un 200 / 404 le remet à zéro.
    L'enrichissement étant parallélisé (`ThreadPoolExecutor`), une fois le
    breaker tripé les fetches restants sont sautés sans coût.
    """
    if breaker is not None and breaker.tripped:
        return None
    try:
        resp = requests.get(
            CROSSREF_MEMBER_URL.format(id=member_id),
            headers={"User-Agent": user_agent},
            timeout=timeout,
        )
        if resp.status_code == 429:
            tripped_before = breaker.tripped if breaker is not None else True
            if breaker is not None:
                breaker.record_failure()
                if breaker.tripped and not tripped_before:
                    logger.warning(
                        "⚡ Coupe-circuit Crossref (429 répétés) : fetches restants sautés, "
                        "retentés au prochain run."
                    )
            logger.warning("Crossref member %d : 429 Too Many Requests", member_id)
            return None
        if resp.status_code == 404:
            if breaker is not None:
                breaker.record_success()
            return None
        resp.raise_for_status()
        body = resp.json()
        if breaker is not None:
            breaker.record_success()
        msg = body.get("message") if isinstance(body, dict) else None
        return msg if isinstance(msg, dict) else None
    except requests.RequestException as e:
        if breaker is not None:
            breaker.record_failure()
        logger.warning("Crossref member fetch failed for %d : %s", member_id, e)
        return None
