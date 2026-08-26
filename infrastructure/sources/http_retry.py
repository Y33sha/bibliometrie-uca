"""Requêtes HTTP avec retry, backoff exponentiel et circuit-breaker, en versions synchrone et asynchrone.

`http_request_with_retry` émet une requête httpx synchrone (extracteurs page à page, clients de préfixes DOI) ; `http_request_with_retry_async` s'appuie sur un `httpx.AsyncClient` partagé entre coroutines (cross-import par DOI, enrichissements concurrents). La politique de décision — backoff, classification des statuts, corps vide, pose du label du breaker — est partagée (`_backoff_delay`, `_is_retryable_status`, `_prepared_label`, `_retry_reason`) ; chaque boucle ne porte que l'I/O de son client et l'attente (`time.sleep` / `asyncio.sleep`).

Politique de retry :
  - 429 (Too Many Requests) et 5xx (panne source) : pause `initial_backoff * 2^attempt` puis retry, jusqu'à `max_retries` ; l'épuisement compte un échec au circuit-breaker. À l'épuisement sous breaker, la version sync coupe la source (`SourceUnavailableError`, l'appelant page à page ne peut pas avancer) ; la version async laisse remonter l'erreur brute, que les appelants concurrents attrapent par requête, l'accumulation coupant au seuil.
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

from application.ports.pipeline.circuit_breaker import SourceUnavailableError
from infrastructure.sources.circuit_breaker import SourceCircuitBreaker, get_current_breaker

logger = logging.getLogger(__name__)


def _backoff_delay(initial_backoff: float, attempt: int) -> float:
    return initial_backoff * (2**attempt)


def _is_retryable_status(status: int) -> bool:
    """429 (rate-limit) et 5xx (panne source) sont retentés ; les autres codes ≥ 400 échouent immédiatement."""
    return status == 429 or 500 <= status < 600


def _prepared_label(label: str) -> tuple[SourceCircuitBreaker | None, str]:
    """Breaker courant et label préfixé du nom de la source.

    Vérifie le breaker s'il existe (il court-circuite la requête via `SourceUnavailableError` quand il a déjà déclenché) et préfixe son nom de source aux logs de retry.
    """
    breaker = get_current_breaker()
    if breaker is not None:
        breaker.check()
        label = f"{breaker.source} {label}".rstrip()
    return breaker, label


def _retry_reason(resp: httpx.Response, *, retry_on_empty_body: bool) -> str | None:
    """Motif de retry d'une réponse aboutie, ou `None` si elle est exploitable.

    Lève immédiatement sur un 4xx non-retryable (échec déterministe, non compté au breaker). Rend un motif pour un statut 429/5xx ou un corps vide.
    """
    if _is_retryable_status(resp.status_code):
        return f"HTTP {resp.status_code}"
    resp.raise_for_status()  # 4xx : échec immédiat, non compté
    if retry_on_empty_body and not resp.text.strip():
        return "corps vide"
    return None


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
    breaker, label = _prepared_label(label)
    last_error: Exception | None = None
    for attempt in range(max_retries):
        is_last = attempt == max_retries - 1
        wait = _backoff_delay(initial_backoff, attempt)
        try:
            resp = httpx.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=headers,
                auth=auth,
                timeout=timeout,
                follow_redirects=True,
            )
        except httpx.RequestError as e:
            last_error = e
            if is_last:
                if breaker is not None:
                    breaker.record_failure()
                    raise SourceUnavailableError(breaker.source) from e
                raise
            logger.warning(
                f"Erreur réseau {label}: {e} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
            )
            time.sleep(wait)
            continue

        reason = _retry_reason(resp, retry_on_empty_body=retry_on_empty_body)
        if reason is None:
            try:
                data = resp.json()
            except json.JSONDecodeError as e:
                last_error = e
                reason = "JSON invalide"
            else:
                if breaker is not None:
                    breaker.record_success()
                return data

        if _is_retryable_status(resp.status_code) and is_last:
            if breaker is not None:
                breaker.record_failure()
                raise SourceUnavailableError(breaker.source)
            resp.raise_for_status()
        logger.warning(
            f"{reason} {label} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
        )
        time.sleep(wait)

    # Boucle épuisée sur corps vide ou JSON invalide répété.
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
    breaker, label = _prepared_label(label)
    last_error: Exception | None = None
    for attempt in range(max_retries):
        is_last = attempt == max_retries - 1
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
            if is_last:
                if breaker is not None:
                    breaker.record_failure()
                raise
            logger.warning(
                f"Erreur réseau {label}: {e} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
            )
            await asyncio.sleep(wait)
            continue

        reason = _retry_reason(resp, retry_on_empty_body=retry_on_empty_body)
        if reason is None:
            try:
                data = resp.json()
            except json.JSONDecodeError as e:
                last_error = e
                reason = "JSON invalide"
            else:
                if breaker is not None:
                    breaker.record_success()
                return data

        if _is_retryable_status(resp.status_code) and is_last:
            if breaker is not None:
                breaker.record_failure()
            resp.raise_for_status()
        logger.warning(
            f"{reason} {label} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
        )
        await asyncio.sleep(wait)

    # Boucle épuisée sur corps vide ou JSON invalide répété.
    if breaker is not None:
        breaker.record_failure()
    logger.error(f"Échec après {max_retries} tentatives {label}")
    if last_error:
        raise last_error
    return {}
