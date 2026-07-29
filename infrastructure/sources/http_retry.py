"""Requêtes HTTP avec retry, backoff exponentiel et circuit-breaker, en versions synchrone et asynchrone.

`http_request_with_retry` s'appuie sur `requests` (extracteurs page à page, clients de préfixes DOI) ; `http_request_with_retry_async` sur un `httpx.AsyncClient` partagé entre coroutines (cross-import par DOI, enrichissements concurrents). Les deux appliquent la même politique.

Politique de retry :
  - 429 (Too Many Requests) et 5xx (panne source) : pause `initial_backoff * 2^attempt` puis retry, jusqu'à `max_retries` ; l'épuisement compte un échec au circuit-breaker.
  - autres 4xx (404…) : échec immédiat, sans retry ni comptage (résultat normal « non trouvé », déterministe).
  - erreur réseau : retry ; l'épuisement compte un échec.
  - corps vide (si `retry_on_empty_body`) ou JSON invalide : retry.

Circuit-breaker : un `SourceCircuitBreaker` posé en ContextVar par la composition root court-circuite les requêtes quand la source cumule trop d'échecs consécutifs, et se remet à zéro au succès.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx
import requests

from application.ports.pipeline.circuit_breaker import SourceUnavailableError
from infrastructure.sources.circuit_breaker import get_current_breaker

logger = logging.getLogger(__name__)


def _backoff_delay(initial_backoff: float, attempt: int) -> float:
    return initial_backoff * (2**attempt)


def _is_retryable_status(status: int) -> bool:
    """429 (rate-limit) et 5xx (panne source) sont retentés ; les autres codes ≥ 400 échouent immédiatement."""
    return status == 429 or 500 <= status < 600


def http_request_with_retry(
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
    headers: dict | None = None,
    auth: tuple | None = None,
    timeout: int = 30,
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    retry_on_empty_body: bool = False,
    label: str = "",
) -> dict:
    """Requête HTTP synchrone avec retry, backoff et circuit-breaker (politique cf. docstring du module).

    `max_retries=3` avec le backoff par défaut donne des pauses de 1, 2, 4 s. `label` : chaîne courte (ex. "year 2024, rec 100") insérée dans les logs. Lève la dernière exception rencontrée si `max_retries` est atteint sans succès.
    """
    breaker = get_current_breaker()
    if breaker is not None:
        breaker.check()
        # Préfixe le nom de la source (porté par le breaker) dans les logs de retry.
        label = f"{breaker.source} {label}".rstrip()

    last_error: Exception | None = None
    for attempt in range(max_retries):
        wait = _backoff_delay(initial_backoff, attempt)
        try:
            resp = requests.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=headers,
                auth=auth,
                timeout=timeout,
            )
        except requests.RequestException as e:
            last_error = e
            if attempt == max_retries - 1:
                if breaker is not None:
                    # Retries épuisés sous breaker : l'appelant sync (extracteur page à page, client de préfixes)
                    # ne peut pas avancer, on court-circuite la source. La variante async, elle, laisse remonter
                    # l'erreur brute (les appelants concurrents l'attrapent par requête et accumulent vers le seuil).
                    breaker.record_failure()
                    raise SourceUnavailableError(breaker.source) from e
                raise
            logger.warning(
                f"Erreur réseau {label}: {e} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
            )
            time.sleep(wait)
            continue

        if _is_retryable_status(resp.status_code):
            if attempt == max_retries - 1:
                if breaker is not None:
                    breaker.record_failure()
                    raise SourceUnavailableError(breaker.source)
                resp.raise_for_status()
            logger.warning(
                f"HTTP {resp.status_code} {label} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
            )
            time.sleep(wait)
            continue

        try:
            resp.raise_for_status()  # autres 4xx : échec immédiat, non compté
        except requests.HTTPError:
            raise

        if retry_on_empty_body and not resp.text.strip():
            logger.warning(
                f"Body vide {label} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
            )
            time.sleep(wait)
            continue

        try:
            data = resp.json()
        except requests.exceptions.JSONDecodeError as e:
            last_error = e
            logger.warning(
                f"JSON invalide {label} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
            )
            time.sleep(wait)
            continue

        if breaker is not None:
            breaker.record_success()
        return data

    # Boucle épuisée sur body vide ou JSON invalide répété.
    if breaker is not None:
        breaker.record_failure()
    logger.error(f"Échec après {max_retries} tentatives {label}")
    if last_error:
        raise last_error
    return {}


async def http_request_with_retry_async(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
    headers: dict | None = None,
    auth: tuple | None = None,
    timeout: float = 30.0,  # noqa: ASYNC109 — wrapper httpx, le timeout est passé au client
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    retry_on_empty_body: bool = False,
    label: str = "",
) -> dict:
    """Requête HTTP asynchrone avec retry, backoff et circuit-breaker (politique cf. docstring du module).

    Le `httpx.AsyncClient` est partagé entre les coroutines d'un même run (connexions poolées). `label` : chaîne courte (ex. "DOI 10.xxx") pour distinguer les requêtes concurrentes dans les logs.
    """
    breaker = get_current_breaker()
    if breaker is not None:
        breaker.check()
        # Préfixe le nom de la source (porté par le breaker) dans les logs de retry.
        label = f"{breaker.source} {label}".rstrip()

    last_error: Exception | None = None
    for attempt in range(max_retries):
        wait = _backoff_delay(initial_backoff, attempt)
        try:
            resp = await client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=headers,
                auth=auth,
                timeout=timeout,
            )
        except httpx.RequestError as e:
            last_error = e
            if attempt == max_retries - 1:
                if breaker is not None:
                    breaker.record_failure()
                raise
            logger.warning(
                f"Erreur réseau {label}: {e} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
            )
            await asyncio.sleep(wait)
            continue

        if _is_retryable_status(resp.status_code):
            if attempt == max_retries - 1:
                if breaker is not None:
                    breaker.record_failure()
                resp.raise_for_status()
            logger.warning(
                f"HTTP {resp.status_code} {label} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
            )
            await asyncio.sleep(wait)
            continue

        try:
            resp.raise_for_status()  # autres 4xx : échec immédiat, non compté
        except httpx.HTTPStatusError:
            raise

        if retry_on_empty_body and not resp.text.strip():
            logger.warning(
                f"Body vide {label} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
            )
            await asyncio.sleep(wait)
            continue

        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            last_error = e
            logger.warning(
                f"JSON invalide {label} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
            )
            await asyncio.sleep(wait)
            continue

        if breaker is not None:
            breaker.record_success()
        return data

    # Boucle épuisée sur body vide ou JSON invalide répété.
    if breaker is not None:
        breaker.record_failure()
    logger.error(f"Échec après {max_retries} tentatives {label}")
    if last_error:
        raise last_error
    return {}
