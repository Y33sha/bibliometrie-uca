"""Requêtes HTTP avec nouvelles tentatives, backoff exponentiel et circuit-breaker, en versions synchrone et asynchrone.

- 429, 5xx, erreur réseau, corps vide (si `retry_on_empty_body`) ou corps illisible : pause de `initial_backoff * 2^attempt`, puis nouvelle tentative, jusqu'à `max_retries` tentatives. L'épuisement compte un échec au circuit-breaker et lève `SourceUnavailableError`.
- Refus temporaire reconnu par la règle de la source (`temporary_refusal`) : pause donnée par la règle, puis nouvelle tentative, sur le même budget de `max_retries` tentatives.
- Autre 4xx (404…) : `httpx2.HTTPStatusError` immédiate, réponse définitive de la source.

Une redirection est suivie seulement pour une requête GET, vers le même hôte, et une fois : Crossref redirige ainsi un DOI alias vers son DOI principal. Toute autre redirection est une erreur : l'hôte joint reste celui qu'`api_params` désigne, et les en-têtes d'authentification ne quittent pas leur destinataire.

Chaque tentative attend son tour au rythme de la source, et compte au circuit-breaker posé par l'accès à la source (`access_source`). Hors de cet accès, une requête lève `RuntimeError`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Iterator, Mapping
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

type Auth = tuple[str, str] | httpx2.Auth
"""Authentification basique, ou flux d'authentification de la source (jeton renouvelé, par exemple)."""

type TemporaryRefusal = Callable[[httpx2.Response], tuple[float, str] | None]
"""Règle d'une source : pause en secondes et motif d'un refus temporaire, ou `None` pour une autre réponse."""


@dataclass(frozen=True, slots=True)
class _Success[T]:
    value: T


@dataclass(frozen=True, slots=True)
class _Refusal:
    """Refus temporaire : nouvelle tentative après la pause demandée par la source."""

    reason: str
    pause: float


def _describe(error: Exception) -> str:
    """Renvoie le type de l'erreur, suivi de son message s'il existe : un délai dépassé de httpx a un message vide."""
    message = str(error)
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


def _backoff_delay(initial_backoff: float, attempt: int) -> float:
    return initial_backoff * float(2**attempt)


def _same_host_redirect(resp: httpx2.Response) -> httpx2.URL | None:
    """Renvoie la destination d'une redirection à suivre, ou `None`.

    Seule une requête GET redirigée vers le même hôte, sous le même schéma et le même port, est suivie.
    """
    if not resp.is_redirect or resp.request.method != "GET":
        return None
    origin = resp.request.url
    target = origin.join(resp.headers["location"])
    if (target.scheme, target.host, target.port) != (origin.scheme, origin.host, origin.port):
        return None
    return target


def _source_breaker(label: str) -> tuple[SourceCircuitBreaker, str]:
    """Renvoie le breaker de la source, et le label préfixé du nom de la source.

    Raises:
        SourceUnavailableError: breaker déjà coupé.
        RuntimeError: requête hors de l'accès à une source.
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
    temporary_refusal: TemporaryRefusal | None = None,
) -> _Success[T] | _Refusal | str:
    """Renvoie l'issue d'une tentative : la valeur décodée, le refus temporaire, ou le motif d'une nouvelle tentative après backoff.

    Lève `httpx2.HTTPStatusError` sur un statut d'erreur définitif.
    """
    if isinstance(result, httpx2.RequestError):
        return f"erreur réseau ({_describe(result)})"
    if temporary_refusal is not None and (refusal := temporary_refusal(result)) is not None:
        pause, reason = refusal
        return _Refusal(reason, pause)
    if result.status_code == 429 or 500 <= result.status_code < 600:
        return f"HTTP {result.status_code}"
    raise_for_status(result)
    if retry_on_empty_body and not result.text.strip():
        return "corps vide"
    try:
        return _Success(decode(result))
    except json.JSONDecodeError:
        return "JSON invalide"


class _Attempts:
    """Tentatives d'une requête : rythme de la source, pause du backoff entre deux tentatives, compte au circuit-breaker."""

    def __init__(self, label: str, max_retries: int, initial_backoff: float) -> None:
        self.breaker, self.label = _source_breaker(label)
        self._max_retries = max_retries
        self._initial_backoff = initial_backoff

    def __iter__(self) -> Iterator[int]:
        return iter(range(self._max_retries))

    def settle[T](self, outcome: _Success[T] | _Refusal | str, attempt: int) -> _Success[T] | float:
        """Renvoie l'issue aboutie, comptée au circuit-breaker, ou la pause avant la tentative suivante.

        Raises:
            SourceUnavailableError: la dernière tentative a échoué ; l'échec est compté au circuit-breaker.
        """
        if isinstance(outcome, _Success):
            self.breaker.record_success()
            return outcome
        reason = outcome.reason if isinstance(outcome, _Refusal) else outcome
        if attempt == self._max_retries - 1:
            self.breaker.record_failure()
            logger.error("Échec après %s tentatives %s : %s", self._max_retries, self.label, reason)
            raise SourceUnavailableError(self.breaker.source)
        wait = (
            outcome.pause
            if isinstance(outcome, _Refusal)
            else _backoff_delay(self._initial_backoff, attempt)
        )
        logger.warning(
            "%s %s — attente %ss (tentative %s/%s)",
            reason,
            self.label,
            wait,
            attempt + 1,
            self._max_retries,
        )
        return wait


def http_request_with_retry(
    method: str,
    url: str,
    *,
    params: QueryParams | None = None,
    json_body: Mapping[str, JsonValue] | None = None,
    headers: Mapping[str, str] | None = None,
    auth: Auth | None = None,
    timeout: int = 30,
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    retry_on_empty_body: bool = False,
    temporary_refusal: TemporaryRefusal | None = None,
    label: str = "",
) -> JsonValue:
    """Envoie une requête HTTP synchrone, selon la politique du module.

    Le corps est renvoyé tel quel : la plupart des sources répondent par un objet, `doi.org/ra` par un tableau. L'appelant convertit le corps dans la forme attendue (`as_mapping`, `as_sequence`).

    Args:
        max_retries: à 3, avec le backoff par défaut, donne des pauses de 1 et 2 s.
        temporary_refusal: règle de la source pour un refus temporaire, retenté après la pause qu'elle donne.
        label: chaîne courte insérée dans le journal (ex. "year 2024, rec 100").
    """
    attempts = _Attempts(label, max_retries, initial_backoff)
    for attempt in attempts:
        if attempts.breaker.pace is not None:
            attempts.breaker.pace.wait()
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
            outcome = _classify(
                resp,
                _json_body,
                retry_on_empty_body=retry_on_empty_body,
                temporary_refusal=temporary_refusal,
            )
        settled = attempts.settle(outcome, attempt)
        if isinstance(settled, _Success):
            return settled.value
        time.sleep(settled)
    raise AssertionError("tentatives sans issue")


async def http_request_with_retry_async(
    client: httpx2.AsyncClient,
    method: str,
    url: str,
    *,
    params: QueryParams | None = None,
    json_body: Mapping[str, JsonValue] | None = None,
    headers: Mapping[str, str] | None = None,
    auth: Auth | None = None,
    timeout: float = 30.0,  # noqa: ASYNC109 — wrapper httpx2, le timeout est passé au client
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    retry_on_empty_body: bool = False,
    label: str = "",
) -> JsonValue:
    """Envoie une requête HTTP asynchrone, selon la politique du module.

    Les coroutines d'un même run partagent le `httpx2.AsyncClient` et ses connexions. Le corps est renvoyé tel quel, comme pour la variante synchrone.

    Args:
        label: chaîne courte pour distinguer les requêtes concurrentes dans le journal (ex. "DOI 10.xxx").
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
    auth: Auth | None = None,
    timeout: float = 30.0,  # noqa: ASYNC109 — wrapper httpx2, le timeout est passé au client
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    retry_on_empty_body: bool = False,
    temporary_refusal: TemporaryRefusal | None = None,
    not_found_statuses: frozenset[int] = frozenset({404}),
    label: str = "",
) -> LookupOutcome[JsonValue]:
    """Interroge une source sur un élément, selon la politique du module, et classe la réponse en issue (cf. `pipeline.http.lookup`).

    Un statut de `not_found_statuses` donne `NOT_FOUND`. Un autre statut d'erreur, des nouvelles tentatives épuisées ou un circuit-breaker déclenché donnent `UNAVAILABLE`.

    Args:
        not_found_statuses: 404 pour une ressource adressée par son identifiant. Vide pour un endpoint de recherche : un 404 désigne alors l'endpoint, et l'absence de l'élément se lit dans une réponse sans résultat.
    """
    try:
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
            temporary_refusal=temporary_refusal,
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
    """Envoie une requête GET asynchrone et renvoie le corps de la réponse en texte (XML, par exemple).

    La politique est celle de `http_request_with_retry_async`. Un corps vide est retenté.
    """
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
    """Renvoie le corps JSON de la réponse. Lève `json.JSONDecodeError` sur un corps illisible, ensuite retenté."""
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
    auth: Auth | None,
    timeout: float,  # noqa: ASYNC109 — wrapper httpx2, le timeout est passé au client
    max_retries: int,
    initial_backoff: float,
    retry_on_empty_body: bool,
    label: str,
    temporary_refusal: TemporaryRefusal | None = None,
) -> T:
    """Exécute la boucle commune des nouvelles tentatives asynchrones.

    Args:
        decode: lit le corps d'une réponse aboutie.
    """
    attempts = _Attempts(label, max_retries, initial_backoff)
    for attempt in attempts:
        if attempts.breaker.pace is not None:
            await attempts.breaker.pace.wait_async()
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
            outcome = _classify(
                resp,
                decode,
                retry_on_empty_body=retry_on_empty_body,
                temporary_refusal=temporary_refusal,
            )
        settled = attempts.settle(outcome, attempt)
        if isinstance(settled, _Success):
            return settled.value
        await asyncio.sleep(settled)
    raise AssertionError("tentatives sans issue")
