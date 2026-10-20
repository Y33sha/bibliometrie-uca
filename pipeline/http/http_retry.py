"""Requêtes HTTP avec retry, backoff exponentiel et circuit-breaker, en versions synchrone et asynchrone.

`http_request_with_retry` émet une requête httpx2 synchrone (moissonneurs page à page, clients de préfixes DOI) ; `http_request_with_retry_async` s'appuie sur un `httpx2.AsyncClient` partagé entre coroutines (recherche par DOI de la phase `fetch_missing`, enrichissements concurrents), et `http_get_text_with_retry_async` rend le corps de la réponse en texte (notices XML du Sudoc). `lookup_json_async` classe la requête d'un élément en issue : trouvé, absent, source indisponible. La politique de décision — backoff, classification des statuts, corps vide, pose du label du breaker — est partagée (`_backoff_delay`, `_is_retryable_status`, `_prepared_label`, `_retry_reason`) ; chaque boucle ne porte que l'I/O de son client et l'attente (`time.sleep` / `asyncio.sleep`).

Politique de retry :
  - 429 (Too Many Requests) et 5xx (panne source) : pause `initial_backoff * 2^attempt` puis retry, jusqu'à `max_retries` ; l'épuisement compte un échec au circuit-breaker. À l'épuisement sous breaker, la version sync coupe la source (`SourceUnavailableError`, l'appelant page à page ne peut pas avancer) ; la version async laisse remonter l'erreur brute, que les appelants concurrents attrapent par requête, l'accumulation coupant au seuil.
  - autres 4xx (404…) : échec immédiat, sans retry ni comptage (résultat normal « non trouvé », déterministe).
  - erreur réseau : retry ; l'épuisement compte un échec.
  - corps vide (si `retry_on_empty_body`) ou JSON invalide : retry.

Une redirection n'est suivie que vers le même hôte, pour une requête GET, et une seule fois : Crossref redirige ainsi un DOI alias vers son DOI principal. Toute autre redirection — autre hôte, autre méthode, second saut — est traitée comme une erreur. L'hôte joint reste celui qu'`api_params` désigne, et les en-têtes d'authentification ne quittent pas leur destinataire.

Circuit-breaker : un `SourceCircuitBreaker` posé en ContextVar par la composition root court-circuite les requêtes quand la source cumule trop d'échecs consécutifs, et se remet à zéro au succès.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Mapping
from typing import cast

import httpx2

from domain.types import JsonValue
from pipeline.http.circuit_breaker import (
    SourceCircuitBreaker,
    SourceUnavailableError,
    get_current_breaker,
)
from pipeline.http.http_status import raise_for_status
from pipeline.http.lookup import NOT_FOUND, UNAVAILABLE, LookupOutcome
from pipeline.http.tls import tls_context

logger = logging.getLogger(__name__)


def _describe(error: Exception) -> str:
    """Type de l'erreur, suivi de son message quand elle en a un : un délai dépassé de httpx a un message vide."""
    message = str(error)
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


def _backoff_delay(initial_backoff: float, attempt: int) -> float:
    return initial_backoff * float(2**attempt)


def _is_retryable_status(status: int) -> bool:
    """429 (rate-limit) et 5xx (panne source) sont retentés ; les autres codes ≥ 400 échouent immédiatement."""
    return status == 429 or 500 <= status < 600


def _same_host_redirect(resp: httpx2.Response) -> httpx2.URL | None:
    """Destination d'une redirection à suivre, ou `None` : seule une requête GET redirigée vers le même hôte, sous le même schéma et le même port, est suivie."""
    if not resp.is_redirect or resp.request.method != "GET":
        return None
    origin = resp.request.url
    target = origin.join(resp.headers["location"])
    if (target.scheme, target.host, target.port) != (origin.scheme, origin.host, origin.port):
        return None
    return target


def _prepared_label(label: str) -> tuple[SourceCircuitBreaker | None, str]:
    """Breaker courant et label préfixé du nom de la source.

    Vérifie le breaker s'il existe (il court-circuite la requête via `SourceUnavailableError` quand il a déjà déclenché) et préfixe son nom de source aux logs de retry.
    """
    breaker = get_current_breaker()
    if breaker is not None:
        breaker.check()
        label = f"{breaker.source} {label}".rstrip()
    return breaker, label


def _retry_reason(resp: httpx2.Response, *, retry_on_empty_body: bool) -> str | None:
    """Motif de retry d'une réponse aboutie, ou `None` si elle est exploitable.

    Lève immédiatement sur un 4xx non-retryable (échec déterministe, non compté au breaker). Rend un motif pour un statut 429/5xx ou un corps vide.
    """
    if _is_retryable_status(resp.status_code):
        return f"HTTP {resp.status_code}"
    raise_for_status(resp)  # 4xx : échec immédiat, non compté
    if retry_on_empty_body and not resp.text.strip():
        return "corps vide"
    return None


def http_request_with_retry(
    method: str,
    url: str,
    *,
    params: Mapping[str, str | int | float | bool | None] | None = None,
    json_body: Mapping[str, JsonValue] | None = None,
    headers: Mapping[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: int = 30,
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    retry_on_empty_body: bool = False,
    label: str = "",
) -> JsonValue:
    """Requête HTTP synchrone avec retry, backoff et circuit-breaker (politique cf. docstring du module).

    `max_retries=3` avec le backoff par défaut donne des pauses de 1, 2, 4 s. `label` : chaîne courte (ex. "year 2024, rec 100") insérée dans les logs. Lève la dernière exception rencontrée si `max_retries` est atteint sans succès. Le corps est rendu tel que la source l'a écrit : la plupart répondent par un objet, `doi.org/ra` par un tableau — l'appelant en tire la forme qu'il attend (`as_mapping`, `as_sequence`).
    """
    breaker, label = _prepared_label(label)
    last_error: Exception | None = None
    for attempt in range(max_retries):
        is_last = attempt == max_retries - 1
        wait = _backoff_delay(initial_backoff, attempt)
        try:
            resp = httpx2.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=headers,
                auth=auth,
                timeout=timeout,
                verify=tls_context(),
            )
            if (target := _same_host_redirect(resp)) is not None:
                resp = httpx2.request(
                    "GET", target, headers=headers, auth=auth, timeout=timeout, verify=tls_context()
                )
        except httpx2.RequestError as e:
            last_error = e
            if is_last:
                if breaker is not None:
                    breaker.record_failure()
                    raise SourceUnavailableError(breaker.source) from e
                raise
            logger.warning(
                "Erreur réseau %s : %s — attente %ss (tentative %s/%s)",
                label,
                _describe(e),
                wait,
                attempt + 1,
                max_retries,
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
                return cast("JsonValue", data)

        if _is_retryable_status(resp.status_code) and is_last:
            if breaker is not None:
                breaker.record_failure()
                raise SourceUnavailableError(breaker.source)
            raise_for_status(resp)
        logger.warning(
            "%s %s — attente %ss (tentative %s/%s)", reason, label, wait, attempt + 1, max_retries
        )
        time.sleep(wait)

    # Boucle épuisée sur corps vide ou JSON invalide répété.
    if breaker is not None:
        breaker.record_failure()
    logger.error("Échec après %s tentatives %s", max_retries, label)
    if last_error:
        raise last_error
    return {}


async def http_request_with_retry_async(
    client: httpx2.AsyncClient,
    method: str,
    url: str,
    *,
    params: Mapping[str, str | int | float | bool | None] | None = None,
    json_body: Mapping[str, JsonValue] | None = None,
    headers: Mapping[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float = 30.0,  # noqa: ASYNC109 — wrapper httpx2, le timeout est passé au client
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    retry_on_empty_body: bool = False,
    label: str = "",
) -> JsonValue:
    """Requête HTTP asynchrone avec retry, backoff et circuit-breaker (politique cf. docstring du module).

    Le `httpx2.AsyncClient` est partagé entre les coroutines d'un même run (connexions poolées). `label` : chaîne courte (ex. "DOI 10.xxx") pour distinguer les requêtes concurrentes dans les logs. Le corps est rendu tel que la source l'a écrit, comme pour la variante synchrone.
    """
    return await _request_with_retry_async(
        client,
        method,
        url,
        decode=_json_body,
        exhausted={},
        params=params,
        json_body=json_body,
        headers=headers,
        auth=auth,
        timeout=timeout,
        max_retries=max_retries,
        initial_backoff=initial_backoff,
        retry_on_empty_body=retry_on_empty_body,
        label=label,
    )


async def lookup_json_async(
    client: httpx2.AsyncClient,
    method: str,
    url: str,
    *,
    params: Mapping[str, str | int | float | bool | None] | None = None,
    json_body: Mapping[str, JsonValue] | None = None,
    headers: Mapping[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float = 30.0,  # noqa: ASYNC109 — wrapper httpx2, le timeout est passé au client
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    retry_on_empty_body: bool = False,
    not_found_statuses: frozenset[int] = frozenset({404}),
    label: str = "",
) -> LookupOutcome[JsonValue]:
    """Requête d'un élément par `http_request_with_retry_async`, classée en issue (cf. `pipeline.http.lookup`).

    Un statut de `not_found_statuses` donne `NOT_FOUND`. Toute autre erreur HTTP, une erreur réseau, une réponse illisible ou un circuit-breaker déclenché donnent `UNAVAILABLE`.

    `not_found_statuses` vaut 404 pour une ressource adressée par son identifiant. Il est vide pour un endpoint de recherche, où un 404 désigne l'endpoint et non l'élément : l'absence s'y lit dans une réponse sans résultat.
    """
    try:
        return await http_request_with_retry_async(
            client,
            method,
            url,
            params=params,
            json_body=json_body,
            headers=headers,
            auth=auth,
            timeout=timeout,
            max_retries=max_retries,
            initial_backoff=initial_backoff,
            retry_on_empty_body=retry_on_empty_body,
            label=label,
        )
    except httpx2.HTTPStatusError as e:
        if e.response.status_code in not_found_statuses:
            return NOT_FOUND
        logger.warning("Indisponible %s : HTTP %s", label, e.response.status_code)
        return UNAVAILABLE
    except SourceUnavailableError:
        return UNAVAILABLE
    except (httpx2.RequestError, json.JSONDecodeError) as e:
        logger.warning("Indisponible %s : %s", label, e)
        return UNAVAILABLE


async def http_get_text_with_retry_async(
    client: httpx2.AsyncClient,
    url: str,
    *,
    params: Mapping[str, str | int | float | bool | None] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30.0,  # noqa: ASYNC109 — wrapper httpx2, le timeout est passé au client
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    label: str = "",
) -> str:
    """Requête GET asynchrone qui rend le corps de la réponse en texte (XML, par exemple), avec la politique de `http_request_with_retry_async`. Un corps vide est retenté."""
    return await _request_with_retry_async(
        client,
        "GET",
        url,
        decode=_text_body,
        exhausted="",
        params=params,
        json_body=None,
        headers=headers,
        auth=None,
        timeout=timeout,
        max_retries=max_retries,
        initial_backoff=initial_backoff,
        retry_on_empty_body=True,
        label=label,
    )


def _json_body(resp: httpx2.Response) -> JsonValue:
    """Corps JSON de la réponse. Lève `json.JSONDecodeError` sur un corps illisible, qui est retenté."""
    return cast("JsonValue", resp.json())


def _text_body(resp: httpx2.Response) -> str:
    return resp.text


async def _request_with_retry_async[T](
    client: httpx2.AsyncClient,
    method: str,
    url: str,
    *,
    decode: Callable[[httpx2.Response], T],
    exhausted: T,
    params: Mapping[str, str | int | float | bool | None] | None,
    json_body: Mapping[str, JsonValue] | None,
    headers: Mapping[str, str] | None,
    auth: tuple[str, str] | None,
    timeout: float,  # noqa: ASYNC109 — wrapper httpx2, le timeout est passé au client
    max_retries: int,
    initial_backoff: float,
    retry_on_empty_body: bool,
    label: str,
) -> T:
    """Boucle de retry asynchrone commune. `decode` lit le corps d'une réponse aboutie ; `exhausted` est rendu quand la boucle s'épuise sur des corps vides sans autre erreur."""
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
            if (target := _same_host_redirect(resp)) is not None:
                resp = await client.request(
                    "GET", target, headers=headers, auth=auth, timeout=timeout
                )
        except httpx2.RequestError as e:
            last_error = e
            if is_last:
                if breaker is not None:
                    breaker.record_failure()
                raise
            logger.warning(
                "Erreur réseau %s : %s — attente %ss (tentative %s/%s)",
                label,
                _describe(e),
                wait,
                attempt + 1,
                max_retries,
            )
            await asyncio.sleep(wait)
            continue

        reason = _retry_reason(resp, retry_on_empty_body=retry_on_empty_body)
        if reason is None:
            try:
                data = decode(resp)
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
            raise_for_status(resp)
        logger.warning(
            "%s %s — attente %ss (tentative %s/%s)", reason, label, wait, attempt + 1, max_retries
        )
        await asyncio.sleep(wait)

    # Boucle épuisée sur corps vide ou JSON invalide répété.
    if breaker is not None:
        breaker.record_failure()
    logger.error("Échec après %s tentatives %s", max_retries, label)
    if last_error:
        raise last_error
    return exhausted
