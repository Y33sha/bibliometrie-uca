"""Accès à l'API OPS de l'Office européen des brevets : jeton d'accès, recherche bibliographique et famille INPADOC.

Le jeton d'accès s'obtient par la clé et le secret de l'application (`client_credentials`) et vaut 20 minutes ; il est renouvelé à l'expiration ou sur un refus 401. OPS règle son débit selon sa charge : en surcharge, il refuse une requête par un 403 (`CLIENT.RobotDetected`) et l'en-tête `X-Throttling-Control` passe au noir. La requête attend alors `OVERLOAD_PAUSE` secondes avant une nouvelle tentative. Un 404 signale une absence ; 429, 5xx et les erreurs réseau sont retentés avec backoff. Chaque tentative suit le rythme et compte au circuit-breaker de l'accès à la source.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

import httpx2

from domain.types import JsonValue, as_int, as_mapping, as_str
from pipeline.http.circuit_breaker import (
    SourceCircuitBreaker,
    SourceUnavailableError,
    get_current_breaker,
)
from pipeline.http.lookup import NOT_FOUND, UNAVAILABLE, LookupOutcome
from pipeline.http.tls import tls_context
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.credentials import get_ops_credentials
from pipeline.ingestion.ops.family import items

logger = logging.getLogger(__name__)

BASE_URL = API_BASE_URLS["ops"]
SEARCH_PAGE = 100
"""Résultats par requête de recherche, plafond de l'API."""
SEARCH_MAX = 2000
"""Rang maximal d'un résultat de recherche."""
OVERLOAD_PAUSE = 70.0
"""Pause après un refus pour surcharge, en secondes : le feu de `X-Throttling-Control` se lit à la minute."""
OVERLOAD_RETRIES = 8
RETRIES = 3
TIMEOUT = 90.0
_TOKEN_MARGIN = 60.0
"""Secondes retranchées à la durée du jeton, pour le renouveler avant son expiration."""


@dataclass(slots=True)
class _Token:
    value: str = ""
    expires_at: float = 0.0


def _number(value: JsonValue) -> int | None:
    """Renvoie un entier écrit par OPS en nombre ou en chaîne (`"1199"`)."""
    text = as_str(value)
    return int(text) if text and text.isdigit() else as_int(value)


_token = _Token()
_token_lock = threading.Lock()


def _store_token(body: JsonValue) -> str:
    data = as_mapping(body)
    _token.value = str(data.get("access_token") or "")
    _token.expires_at = time.monotonic() + (_number(data.get("expires_in")) or 1200) - _TOKEN_MARGIN
    return _token.value


def _token_request() -> tuple[str, dict[str, str], tuple[str, str]]:
    return (
        f"{BASE_URL}/auth/accesstoken",
        {"grant_type": "client_credentials"},
        get_ops_credentials(),
    )


def _valid_token() -> str | None:
    return _token.value if _token.value and time.monotonic() < _token.expires_at else None


def _token_sync() -> str:
    with _token_lock:
        if token := _valid_token():
            return token
        url, data, auth = _token_request()
        resp = httpx2.post(url, data=data, auth=auth, timeout=TIMEOUT, verify=tls_context())
        resp.raise_for_status()
        return _store_token(resp.json())


async def _token_async(client: httpx2.AsyncClient) -> str:
    if token := _valid_token():
        return token
    url, data, auth = _token_request()
    resp = await client.post(url, data=data, auth=auth, timeout=TIMEOUT)
    resp.raise_for_status()
    return _store_token(resp.json())


def _expire_token() -> None:
    _token.expires_at = 0.0


@dataclass(frozen=True, slots=True)
class _Retry:
    """Nouvelle tentative : pause, et décompte sur le budget des surcharges ou des erreurs."""

    pause: float
    overload: bool
    reason: str


type _Outcome = JsonValue | _Retry | None
"""Corps JSON, nouvelle tentative, ou `None` pour une absence (404)."""


def _classify(result: httpx2.Response | httpx2.RequestError, attempt: int) -> _Outcome:
    if isinstance(result, httpx2.RequestError):
        return _Retry(2.0**attempt, False, f"erreur réseau ({type(result).__name__})")
    status = result.status_code
    if status == 200:
        return cast("JsonValue", result.json())
    if status == 404:
        return None
    if status in (400, 401) and "token" in result.text.lower():
        _expire_token()
        return _Retry(0.0, False, "jeton expiré")
    if status == 403 and (
        "RobotDetected" in result.text or "black" in result.headers.get("x-throttling-control", "")
    ):
        return _Retry(
            OVERLOAD_PAUSE, True, f"surcharge ({result.headers.get('x-throttling-control', '')})"
        )
    if status == 429 or status >= 500:
        return _Retry(2.0**attempt, False, f"HTTP {status}")
    result.raise_for_status()
    return None


class _Attempts:
    """Budget de tentatives d'une requête : `RETRIES` erreurs, `OVERLOAD_RETRIES` refus pour surcharge."""

    def __init__(self, label: str) -> None:
        breaker = get_current_breaker()
        if breaker is None:
            raise RuntimeError("requête OPS hors de l'accès à une source (`access_source`)")
        breaker.check()
        self.breaker: SourceCircuitBreaker = breaker
        self.label = label
        self.errors = 0
        self.overloads = 0

    def settle(self, outcome: _Outcome) -> _Outcome:
        """Renvoie l'issue, ou la nouvelle tentative à faire.

        Raises:
            SourceUnavailableError: budget épuisé ; l'échec est compté au circuit-breaker.
        """
        if not isinstance(outcome, _Retry):
            self.breaker.record_success()
            return outcome
        if outcome.overload:
            self.overloads += 1
            exhausted = self.overloads >= OVERLOAD_RETRIES
        else:
            self.errors += 1
            exhausted = self.errors >= RETRIES
        if exhausted:
            self.breaker.record_failure()
            logger.error("OPS %s : %s, tentatives épuisées", self.label, outcome.reason)
            raise SourceUnavailableError(self.breaker.source)
        logger.warning("OPS %s : %s — pause de %ss", self.label, outcome.reason, outcome.pause)
        return outcome


def get_json(
    path: str, params: Mapping[str, str] | None = None, *, label: str = ""
) -> JsonValue | None:
    """Envoie une requête GET synchrone à OPS et renvoie le corps JSON, ou `None` pour une absence (404)."""
    attempts = _Attempts(label or path)
    attempt = 0
    while True:
        if attempts.breaker.pace is not None:
            attempts.breaker.pace.wait()
        headers = {"Authorization": f"Bearer {_token_sync()}", "Accept": "application/json"}
        try:
            result: httpx2.Response | httpx2.RequestError = httpx2.get(
                f"{BASE_URL}{path}",
                params=params,
                headers=headers,
                timeout=TIMEOUT,
                verify=tls_context(),
            )
        except httpx2.RequestError as e:
            result = e
        outcome = attempts.settle(_classify(result, attempt))
        if not isinstance(outcome, _Retry):
            return outcome
        time.sleep(outcome.pause)
        attempt += 1


async def get_json_async(
    client: httpx2.AsyncClient,
    path: str,
    params: Mapping[str, str] | None = None,
    *,
    label: str = "",
) -> LookupOutcome[JsonValue]:
    """Envoie une requête GET asynchrone à OPS et renvoie le corps JSON, `NOT_FOUND` ou `UNAVAILABLE`."""
    try:
        attempts = _Attempts(label or path)
    except SourceUnavailableError:
        return UNAVAILABLE
    attempt = 0
    while True:
        if attempts.breaker.pace is not None:
            await attempts.breaker.pace.wait_async()
        try:
            headers = {
                "Authorization": f"Bearer {await _token_async(client)}",
                "Accept": "application/json",
            }
            result: httpx2.Response | httpx2.RequestError = await client.get(
                f"{BASE_URL}{path}", params=params, headers=headers, timeout=TIMEOUT
            )
        except httpx2.RequestError as e:
            result = e
        try:
            outcome = attempts.settle(_classify(result, attempt))
        except SourceUnavailableError, httpx2.HTTPStatusError:
            return UNAVAILABLE
        if outcome is None:
            return NOT_FOUND
        if not isinstance(outcome, _Retry):
            return outcome
        await asyncio.sleep(outcome.pause)
        attempt += 1


SEARCH_PATH = "/rest-services/published-data/search/biblio"


def family_path(publication: str) -> str:
    """Chemin de la famille INPADOC d'un numéro de publication epodoc (`FR3053353`), avec la bibliographie de chaque membre."""
    return f"/rest-services/family/publication/epodoc/{publication}/biblio"


def search_params(query: str, start: int) -> dict[str, str]:
    """Paramètres d'une page de recherche CQL à partir du rang `start` (1 pour la première)."""
    return {"q": query, "Range": f"{start}-{start + SEARCH_PAGE - 1}"}


@dataclass(frozen=True, slots=True)
class SearchHit:
    """Publication trouvée par une recherche, avec sa famille docdb et ses déposants."""

    family_id: str
    publication: str
    """Numéro epodoc de la publication, sans code de type (`FR3053353`)."""
    priority_dates: tuple[str, ...]
    applicants: tuple[str, ...]


def search_page(body: JsonValue) -> tuple[int, list[SearchHit]]:
    """Décode une page de recherche : nombre total de résultats et publications trouvées."""
    search = as_mapping(
        as_mapping(as_mapping(body).get("ops:world-patent-data")).get("ops:biblio-search")
    )
    total = _number(search.get("@total-result-count")) or 0
    hits = []
    for doc in items(as_mapping(search.get("ops:search-result")).get("exchange-documents")):
        for raw in items(as_mapping(doc).get("exchange-document")):
            ex = as_mapping(raw)
            biblio = as_mapping(ex.get("bibliographic-data"))
            dates = [
                str(value)
                for claim in items(as_mapping(biblio.get("priority-claims")).get("priority-claim"))
                for d in items(as_mapping(claim).get("document-id"))
                if (value := as_mapping(as_mapping(d).get("date")).get("$")) is not None
            ]
            applicants = [
                str(
                    as_mapping(as_mapping(as_mapping(a).get("applicant-name")).get("name")).get("$")
                    or ""
                )
                for a in items(
                    as_mapping(as_mapping(biblio.get("parties")).get("applicants")).get("applicant")
                )
            ]
            hits.append(
                SearchHit(
                    family_id=str(ex.get("@family-id") or ""),
                    publication=f"{ex.get('@country') or ''}{ex.get('@doc-number') or ''}",
                    priority_dates=tuple(dates),
                    applicants=tuple(a for a in applicants if a),
                )
            )
    return total, hits
