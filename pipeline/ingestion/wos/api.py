"""Accès à l'API Web of Science Expanded : moissonnage et recherche Advanced Search (`usrQuery`), authentifiés par la clé d'API."""

from __future__ import annotations

from collections.abc import Mapping

import httpx2

from domain.types import JsonValue, as_int, as_mapping, as_sequence, at_path
from pipeline.http.http_retry import http_request_with_retry, lookup_json_async
from pipeline.http.lookup import UNAVAILABLE, LookupOutcome, NotFound, Unavailable
from pipeline.http.tls import tls_context
from pipeline.ingestion.api_params import API_BASE_URLS, WOS_PER_PAGE
from pipeline.ingestion.credentials import get_wos_api_key

type QueryParams = Mapping[str, str | int | float | bool | None]


def build_query(year: int, affiliations: list[str]) -> str:
    """Construit la requête WoS Advanced Search pour une année donnée.

    Filtre `OG=(...)` (Organization-Enhanced, OR sur les variantes d'affiliation) et `PY=<year>`. `affiliations` doit être non vide : sans organisations, l'API WoS répond 400 Bad Request sur `OG=()`.
    """
    if not affiliations:
        raise ValueError("build_query: affiliations vide (la requête WoS exige au moins une org)")
    orgs = " OR ".join(affiliations)
    return f"OG=({orgs}) AND PY=({year})"


def get_records(data: Mapping[str, JsonValue]) -> list[Mapping[str, JsonValue]]:
    """Extrait la liste de records depuis la réponse API WoS.

    Chemin profond `data.Data.Records.records.REC`, liste ou objet unique. Retourne `[]` si n'importe quel niveau manque (réponse mal formée ou vide).
    """
    records = at_path(data, "Data", "Records", "records").get("REC")
    return [
        as_mapping(r) for r in ([records] if isinstance(records, Mapping) else as_sequence(records))
    ]


def get_records_found(data: Mapping[str, JsonValue]) -> int:
    """Extrait le nombre total de records trouvés depuis la réponse API WoS."""
    return as_int(as_mapping(data.get("QueryResult")).get("RecordsFound")) or 0


# Préfixes DOI systématiquement absents de WoS — preprints / repositories qui ne sont pas indexés. Filtrés côté client pour éviter les appels inutiles dans `fetch_missing_doi`.
_WOS_UNINDEXED_DOI_PREFIXES = ("10.48550/", "10.2139/", "10.21203/", "10.5281/zenodo")


def filter_doi_for_wos(doi: str) -> str | None:
    """Écarte un DOI (déjà normalisé par `clean_doi`) non interrogeable sur WoS.

    Retourne `None` si :

    - le DOI est dans `_WOS_UNINDEXED_DOI_PREFIXES` (preprints Zenodo, arXiv, SSRN, Research Square) — WoS ne les indexe pas ;
    - le DOI contient `"` ou newline (casserait la requête WoS).

    Sinon retourne le DOI tel quel. La normalisation (préfixe URL, casse, encodage, suffixes) est faite en amont par `clean_doi` : ici, uniquement le filtrage propre à WoS.
    """
    if any(doi.startswith(p) for p in _WOS_UNINDEXED_DOI_PREFIXES):
        return None
    if '"' in doi or "\n" in doi:
        return None
    return doi


def headers(api_key: str) -> dict[str, str]:
    """En-têtes d'une requête WoS : clé d'API, réponse JSON."""
    return {"X-ApiKey": api_key, "Accept": "application/json"}


class WosClient:
    """Client de l'API WoS Expanded.

    Le backoff est plus long qu'aux autres sources (`initial_backoff=2.0`) : WoS renvoie plus volontiers des 429.
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        self._url = base_url
        self._headers = headers(api_key)

    def _get(self, params: QueryParams, label: str) -> Mapping[str, JsonValue]:
        return as_mapping(
            http_request_with_retry(
                "GET",
                self._url,
                params=params,
                headers=self._headers,
                timeout=60,
                retry_on_empty_body=True,
                initial_backoff=2.0,
                label=label,
            )
        )

    def fetch_page(
        self, year: int, first_record: int, affiliations: list[str]
    ) -> Mapping[str, JsonValue]:
        """Une page de records, à partir du rang `first_record`."""
        params: QueryParams = {
            "databaseId": "WOS",
            "usrQuery": build_query(year, affiliations),
            "count": WOS_PER_PAGE,
            "firstRecord": first_record,
        }
        return self._get(params, label=f"({year}, rec {first_record})")

    def count(self, year: int, affiliations: list[str]) -> int:
        """Nombre de records d'une année, lu sur une recherche qui n'en renvoie aucun (`count=0`)."""
        params: QueryParams = {
            "databaseId": "WOS",
            "usrQuery": build_query(year, affiliations),
            "count": 0,
            "firstRecord": 1,
        }
        return get_records_found(self._get(params, label=f"({year}, comptage)"))

    def check_quota(self) -> str | None:
        """Quota annuel restant (en-tête `X-REC-AmtPerYear-Remaining`), ou `None` s'il est illisible.

        Lève `RuntimeError` si l'API refuse la clé (401/403).
        """
        resp = httpx2.get(
            self._url,
            headers=self._headers,
            params={"databaseId": "WOS", "usrQuery": "OG=(test)", "count": "0", "firstRecord": "1"},
            timeout=30,
            verify=tls_context(),
        )
        if resp.status_code in (401, 403):
            raise RuntimeError(
                f"Erreur d'authentification WoS ({resp.status_code}). "
                f"Vérifier la clé API. Réponse : {resp.text[:300]}"
            )
        if resp.status_code != 200:
            return None
        remaining: str | None = resp.headers.get("X-REC-AmtPerYear-Remaining")
        return remaining


async def search(
    client: httpx2.AsyncClient,
    usr_query: str,
    *,
    first_record: int = 1,
    count: int = WOS_PER_PAGE,
    label: str,
) -> LookupOutcome[Mapping[str, JsonValue]]:
    """Une page de la recherche `usr_query`, à partir du rang `first_record`.

    `NOT_FOUND` : WoS répond 400 à une requête sans correspondance. Un corps vide compte pour une source indisponible. Le backoff initial de 4 s donne la séquence 4, 8, 16, 32, 64.
    """
    outcome = await lookup_json_async(
        client,
        "GET",
        API_BASE_URLS["wos"],
        headers=headers(get_wos_api_key()),
        params={
            "databaseId": "WOS",
            "usrQuery": usr_query,
            "count": count,
            "firstRecord": first_record,
        },
        timeout=60,
        initial_backoff=4.0,
        retry_on_empty_body=True,
        not_found_statuses=frozenset({400}),
        label=label,
    )
    if isinstance(outcome, NotFound | Unavailable):
        return outcome
    data = as_mapping(outcome)
    return data if data else UNAVAILABLE
