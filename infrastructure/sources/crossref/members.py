"""Client API Crossref Members — `GET /members/{id}`.

Consommé par `application.services.publishers.enrichment.from_crossref_members`
(fallback `country` quand OpenAlex Publishers n'a pas de match) et par
l'audit `audit_crossref_member_countries`.

Polite pool via header `User-Agent` (mailto), cohérent avec les autres
clients Crossref du projet (`doi_prefixes/clients.py`,
`crossref/fetch_missing_doi.py`).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from infrastructure.sources.circuit_breaker import SourceCircuitBreaker

CROSSREF_MEMBER_URL = "https://api.crossref.org/members/{id}"

_MAX_RETRIES = 3
_INITIAL_BACKOFF_S = 1.0


def fetch_crossref_member(
    member_id: int,
    *,
    user_agent: str,
    logger: logging.Logger,
    timeout: float = 15.0,
    breaker: SourceCircuitBreaker | None = None,
) -> dict[str, Any] | None:
    """GET sur `api.crossref.org/members/{id}`.

    Retourne le bloc `message` (= record du member) ou `None` sur 404
    / erreur réseau persistante.

    Retry + backoff exponentiel (`_INITIAL_BACKOFF_S * 2^attempt`) sur 429 et sur
    panne réseau/5xx, comme les autres clients Crossref du projet
    (`http_request_with_retry`) : un 429 ponctuel se rattrape sans perdre le member
    ni pénaliser le coupe-circuit. L'appelant interroge en **séquentiel** (pas de
    fan-out parallèle qui bursterait au-dessus du quota polite pool).

    Coupe-circuit (budget Crossref) : si `breaker` est fourni et **déclenché**, on ne
    tape plus l'API (retourne `None` immédiatement). Un échec *définitif* (429 ou
    panne après épuisement des retries) compte un échec ; un 200 / 404 le remet à
    zéro. Une fois le breaker déclenché, les fetches restants sont sautés sans coût.
    """
    if breaker is not None and breaker.tripped:
        return None

    last_error: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        backoff = _INITIAL_BACKOFF_S * (2**attempt)
        last_attempt = attempt == _MAX_RETRIES - 1
        try:
            resp = requests.get(
                CROSSREF_MEMBER_URL.format(id=member_id),
                headers={"User-Agent": user_agent},
                timeout=timeout,
            )
            if resp.status_code == 429:
                if not last_attempt:
                    time.sleep(backoff)
                    continue
                _record_definitive_failure(breaker, logger)
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
            last_error = e
            if not last_attempt:
                time.sleep(backoff)
                continue
            _record_definitive_failure(breaker, logger)
            logger.warning("Crossref member fetch failed for %d : %s", member_id, last_error)
            return None
    return None


def _record_definitive_failure(
    breaker: SourceCircuitBreaker | None, logger: logging.Logger
) -> None:
    """Compte un échec définitif au coupe-circuit et logue son éventuel déclenchement."""
    if breaker is None:
        return
    tripped_before = breaker.tripped
    breaker.record_failure()
    if breaker.tripped and not tripped_before:
        logger.warning(
            "⚡ Coupe-circuit Crossref (429/pannes répétés) : fetches restants sautés, "
            "retentés au prochain run."
        )
