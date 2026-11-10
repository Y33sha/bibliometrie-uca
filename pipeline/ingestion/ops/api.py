"""Accès à l'API OPS de l'Office européen des brevets : recherche bibliographique et famille INPADOC.

Les requêtes suivent la politique commune de `pipeline.http.http_retry`. Le flux d'authentification `OpsAuth` obtient le jeton d'accès par la clé et le secret de l'application (`client_credentials`), le joint à chaque requête et le renouvelle sur un refus 401. En surcharge, OPS refuse une requête par un 403 et passe au noir le feu du service dans l'en-tête `X-Throttling-Control` : la requête est retentée après `OVERLOAD_PAUSE` secondes (`overload_refusal`). Les recherches, limitées à quelques requêtes par minute quand OPS est chargé, partent au plus une toutes les `SEARCH_INTERVAL` secondes.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Generator, Mapping
from dataclasses import dataclass

import httpx2

from domain.types import JsonValue, as_int, as_mapping, as_str
from pipeline.http.http_retry import http_request_with_retry, lookup_json_async
from pipeline.http.lookup import LookupOutcome
from pipeline.http.pace import Pace
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.credentials import get_ops_credentials
from pipeline.ingestion.ops.family import items

BASE_URL = API_BASE_URLS["ops"]
SEARCH_PATH = "/rest-services/published-data/search/biblio"
SEARCH_PAGE = 100
"""Résultats par requête de recherche, plafond de l'API."""
SEARCH_MAX = 2000
"""Rang maximal d'un résultat de recherche."""
SEARCH_INTERVAL = 12.0
"""Secondes entre deux recherches : OPS chargé accepte environ 5 recherches par minute."""
OVERLOAD_PAUSE = 70.0
"""Pause après un refus pour surcharge, en secondes : le feu de `X-Throttling-Control` se lit à la minute."""
TIMEOUT = 90
_HEADERS = {"Accept": "application/json"}
_TOKEN_MARGIN = 60.0
"""Secondes retranchées à la durée du jeton, pour le renouveler avant son expiration."""


def _number(value: JsonValue) -> int | None:
    """Renvoie un entier écrit par OPS en nombre ou en chaîne (`"1199"`)."""
    text = as_str(value)
    return int(text) if text and text.isdigit() else as_int(value)


class OpsAuth(httpx2.Auth):
    """Flux d'authentification d'OPS : jeton demandé au premier besoin et à son expiration, joint à chaque requête, renouvelé sur un refus 401."""

    requires_response_body = True

    def __init__(self) -> None:
        self._token = ""
        self._expires_at = 0.0

    def _token_request(self) -> httpx2.Request:
        key, secret = get_ops_credentials()
        basic = base64.b64encode(f"{key}:{secret}".encode()).decode()
        return httpx2.Request(
            "POST",
            f"{BASE_URL}/auth/accesstoken",
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {basic}"},
        )

    def _store(self, response: httpx2.Response) -> None:
        data = as_mapping(response.json()) if response.status_code == 200 else {}
        self._token = str(data.get("access_token") or "")
        lifetime = _number(data.get("expires_in")) or 1200
        self._expires_at = time.monotonic() + lifetime - _TOKEN_MARGIN

    def auth_flow(self, request: httpx2.Request) -> Generator[httpx2.Request, httpx2.Response]:
        if not self._token or time.monotonic() >= self._expires_at:
            self._store((yield self._token_request()))
        request.headers["Authorization"] = f"Bearer {self._token}"
        response = yield request
        if response.status_code == 401:
            self._store((yield self._token_request()))
            request.headers["Authorization"] = f"Bearer {self._token}"
            yield request


AUTH = OpsAuth()
_SEARCH_PACE = Pace(1 / SEARCH_INTERVAL)


def overload_refusal(response: httpx2.Response) -> tuple[float, str] | None:
    """Renvoie la pause et le motif d'un refus pour surcharge (403, feu noir), `None` pour une autre réponse."""
    throttling = response.headers.get("x-throttling-control", "")
    if response.status_code == 403 and ("RobotDetected" in response.text or "black" in throttling):
        return OVERLOAD_PAUSE, "service saturé (feu noir)"
    return None


def get_json(
    path: str, params: Mapping[str, str] | None = None, *, label: str = ""
) -> JsonValue | None:
    """Envoie une requête GET synchrone à OPS et renvoie le corps JSON, ou `None` pour une absence (404)."""
    if path == SEARCH_PATH:
        _SEARCH_PACE.wait()
    try:
        return http_request_with_retry(
            "GET",
            f"{BASE_URL}{path}",
            params=params,
            headers=_HEADERS,
            auth=AUTH,
            timeout=TIMEOUT,
            temporary_refusal=overload_refusal,
            label=label,
        )
    except httpx2.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise


async def get_json_async(
    client: httpx2.AsyncClient,
    path: str,
    params: Mapping[str, str] | None = None,
    *,
    wait_on_overload: bool = True,
    label: str = "",
) -> LookupOutcome[JsonValue]:
    """Envoie une requête GET asynchrone à OPS et renvoie le corps JSON, `NOT_FOUND` ou `UNAVAILABLE`.

    Args:
        wait_on_overload: retente un refus pour surcharge après `OVERLOAD_PAUSE` secondes. Faux : le refus donne `UNAVAILABLE`, et l'élément attend le run suivant.
    """
    if path == SEARCH_PATH:
        await _SEARCH_PACE.wait_async()
    return await lookup_json_async(
        client,
        "GET",
        f"{BASE_URL}{path}",
        params=params,
        headers=_HEADERS,
        auth=AUTH,
        timeout=TIMEOUT,
        temporary_refusal=overload_refusal if wait_on_overload else None,
        label=label,
    )


def family_path(publication: str) -> str:
    """Chemin de la famille INPADOC d'un numéro de publication sans code de type (`FR3053353` → `FR.3053353`, au format docdb), avec la bibliographie de chaque membre."""
    return f"/rest-services/family/publication/docdb/{publication[:2]}.{publication[2:]}/biblio"


def publication_forms(publication: str) -> list[str]:
    """Renvoie les écritures OPS possibles d'un numéro de publication. Une demande américaine publiée s'écrit avec ou sans le zéro qui suit l'année, selon l'année (`US2024211607` → `US20240211607`, puis `US2024211607`)."""
    digits = publication[2:]
    if publication.startswith("US") and len(digits) == 10 and digits.startswith("20"):
        return [f"US{digits[:4]}0{digits[4:]}", publication]
    return [publication]


def application_family_path(application: str) -> str | None:
    """Chemin de la famille INPADOC d'un numéro de demande au format docdb (`FR1658141` → `FR.1658141`). `None` pour une demande internationale, écrite sans son office de dépôt."""
    if application.startswith("WO"):
        return None
    return f"/rest-services/family/application/docdb/{application[:2]}.{application[2:]}/biblio"


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
