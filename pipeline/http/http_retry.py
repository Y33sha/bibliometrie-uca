"""Requêtes HTTP avec nouvelles tentatives, backoff exponentiel et circuit-breaker, en versions synchrone et asynchrone.

- 429, 5xx, erreur réseau, corps vide (si `retry_on_empty_body`) ou corps illisible : pause de `initial_backoff * 2^attempt`, puis nouvelle tentative, jusqu'à `max_retries` tentatives. L'épuisement compte un échec au circuit-breaker et lève `SourceUnavailableError`.
- Autre 4xx (404…) : `httpx2.HTTPStatusError` immédiate, réponse définitive de la source.

Une redirection est suivie seulement pour une requête GET, vers le même hôte, et une fois : Crossref redirige ainsi un DOI alias vers son DOI principal. Toute autre redirection est une erreur : l'hôte joint reste celui qu'`api_params` désigne, et les en-têtes d'authentification ne quittent pas leur destinataire.

Chaque tentative attend son tour au rythme de la source, et compte au circuit-breaker que pose l'accès à la source (`access_source`). Hors de cet accès, une requête lève `RuntimeError`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
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

type QueryParams = Mapping[str, str | int | float | bool | None]


@dataclass(frozen=True, slots=True)
class _Success[T]:
    value: T


def _describe(error: Exception) -> str:
    """Type de l'erreur, suivi de son message quand elle en a un : un délai dépassé de httpx a un message vide."""
    message = str(error)
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


def _backoff_delay(initial_backoff: float, attempt: int) -> float:
    return initial_backoff * float(2**attempt)


def _same_host_redirect(resp: httpx2.Response) -> httpx2.URL | None:
    """Destination d'une redirection à suivre, ou `None` : seule une requête GET redirigée vers le même hôte, sous le même schéma et le même port, est suivie."""
    if not resp.is_redirect or resp.request.method != "GET":
        return None
    origin = resp.request.url
    target = origin.join(resp.headers["location"])
    if (target.scheme, target.host, target.port) != (origin.scheme, origin.host, origin.port):
        return None
    return target


def _source_breaker(label: str) -> tuple[SourceCircuitBreaker, str]:
    """Breaker de la source et label préfixé de son nom.

    Lève `SourceUnavailableError` si le breaker a déjà coupé, et `RuntimeError` hors de l'accès à une source.
    """
    breaker = get_current_breaker()
    if breaker is None:
        raise RuntimeError("requête HTTP hors de l'accès à une source (`access_source`)")
    breaker.check()
    return breaker, f"{breaker.source} {label}".rstrip()


def _classify[T](
    result: httpx2.Response | httpx2.RequestError,
    decode: Callable[[httpx2.Response], T],
    *,
    retry_on_empty_body: bool,
) -> _Success[T] | str:
    """Issue d'une tentative : la valeur décodée, ou le motif d'un retry.

    Lève `httpx2.HTTPStatusError` sur un statut d'erreur non retryable : la réponse est définitive.
    """
    if isinstance(result, httpx2.RequestError):
        return f"erreur réseau ({_describe(result)})"
    if result.status_code == 429 or 500 <= result.status_code < 600:
        return f"HTTP {result.status_code}"
    raise_for_status(result)
    if retry_on_empty_body and not result.text.strip():
        return "corps vide"
    try:
        return _Success(decode(result))
    except json.JSONDecodeError:
        return "JSON invalide"


def _log_retry(reason: str, label: str, wait: float, attempt: int, max_retries: int) -> None:
    logger.warning(
        "%s %s — attente %ss (tentative %s/%s)", reason, label, wait, attempt + 1, max_retries
    )


def _exhausted(
    breaker: SourceCircuitBreaker, label: str, reason: str, max_retries: int
) -> SourceUnavailableError:
    """Compte l'échec au breaker et rend l'erreur à lever."""
    breaker.record_failure()
    logger.error("Échec après %s tentatives %s : %s", max_retries, label, reason)
    return SourceUnavailableError(breaker.source)


def http_request_with_retry(
    method: str,
    url: str,
    *,
    params: QueryParams | None = None,
    json_body: Mapping[str, JsonValue] | None = None,
    headers: Mapping[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: int = 30,
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    retry_on_empty_body: bool = False,
    label: str = "",
) -> JsonValue:
    """Requête HTTP synchrone, selon la politique du module.

    `max_retries=3` avec le backoff par défaut donne des pauses de 1 et 2 s. `label` : chaîne courte (ex. "year 2024, rec 100") insérée dans les logs. Le corps est rendu tel que la source l'a écrit : la plupart répondent par un objet, `doi.org/ra` par un tableau — l'appelant en tire la forme qu'il attend (`as_mapping`, `as_sequence`).
    """
    breaker, label = _source_breaker(label)
    reason = ""
    for attempt in range(max_retries):
        if breaker.pace is not None:
            breaker.pace.wait()
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
            outcome = _classify(e, _json_body, retry_on_empty_body=retry_on_empty_body)
        else:
            outcome = _classify(resp, _json_body, retry_on_empty_body=retry_on_empty_body)
        if isinstance(outcome, _Success):
            breaker.record_success()
            return outcome.value
        reason = outcome
        if attempt < max_retries - 1:
            wait = _backoff_delay(initial_backoff, attempt)
            _log_retry(reason, label, wait, attempt, max_retries)
            time.sleep(wait)
    raise _exhausted(breaker, label, reason, max_retries)


async def http_request_with_retry_async(
    client: httpx2.AsyncClient,
    method: str,
    url: str,
    *,
    params: QueryParams | None = None,
    json_body: Mapping[str, JsonValue] | None = None,
    headers: Mapping[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float = 30.0,  # noqa: ASYNC109 — wrapper httpx2, le timeout est passé au client
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    retry_on_empty_body: bool = False,
    label: str = "",
) -> JsonValue:
    """Requête HTTP asynchrone, selon la politique du module.

    Les coroutines d'un même run partagent le `httpx2.AsyncClient` et ses connexions. `label` : chaîne courte (ex. "DOI 10.xxx") pour distinguer les requêtes concurrentes dans les logs. Le corps est rendu tel que la source l'a écrit, comme pour la variante synchrone.
    """
    return await _request_with_retry_async(
        client,
        method,
        url,
        decode=_json_body,
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
    params: QueryParams | None = None,
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

    Un statut de `not_found_statuses` donne `NOT_FOUND`. Un autre statut d'erreur, des retries épuisés ou un circuit-breaker déclenché donnent `UNAVAILABLE`.

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


async def http_get_text_with_retry_async(
    client: httpx2.AsyncClient,
    url: str,
    *,
    params: QueryParams | None = None,
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
    params: QueryParams | None,
    json_body: Mapping[str, JsonValue] | None,
    headers: Mapping[str, str] | None,
    auth: tuple[str, str] | None,
    timeout: float,  # noqa: ASYNC109 — wrapper httpx2, le timeout est passé au client
    max_retries: int,
    initial_backoff: float,
    retry_on_empty_body: bool,
    label: str,
) -> T:
    """Boucle de retry asynchrone commune. `decode` lit le corps d'une réponse aboutie."""
    breaker, label = _source_breaker(label)
    reason = ""
    for attempt in range(max_retries):
        if breaker.pace is not None:
            await breaker.pace.wait_async()
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
            outcome = _classify(e, decode, retry_on_empty_body=retry_on_empty_body)
        else:
            outcome = _classify(resp, decode, retry_on_empty_body=retry_on_empty_body)
        if isinstance(outcome, _Success):
            breaker.record_success()
            return outcome.value
        reason = outcome
        if attempt < max_retries - 1:
            wait = _backoff_delay(initial_backoff, attempt)
            _log_retry(reason, label, wait, attempt, max_retries)
            await asyncio.sleep(wait)
    raise _exhausted(breaker, label, reason, max_retries)
