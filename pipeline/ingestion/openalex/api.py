"""Accès à l'API OpenAlex : identifiants des requêtes, moissonnage de `/works`, lecture d'un work par son identifiant ou son DOI."""

from __future__ import annotations

from collections.abc import Mapping

import httpx2

from domain.types import JsonValue, as_int, as_mapping, as_sequence, at_path
from pipeline.http.http_retry import http_request_with_retry, lookup_json_async
from pipeline.http.lookup import NOT_FOUND, UNAVAILABLE, LookupOutcome, NotFound, Unavailable
from pipeline.http.polite_pool import get_polite_pool_email_optional
from pipeline.ingestion.api_params import API_BASE_URLS, OPENALEX_PER_PAGE
from pipeline.ingestion.credentials import get_openalex_api_key

type QueryParams = Mapping[str, str | int | float | bool | None]

SELECT_FIELDS = ",".join(
    [
        "id",
        "doi",
        "title",
        "display_name",
        "publication_year",
        "publication_date",
        "type",
        "language",
        "primary_location",
        "locations",
        "authorships",
        "open_access",
        "cited_by_count",
        "fwci",
        "citation_normalized_percentile",
        "biblio",
        "is_retracted",
        "topics",
        "keywords",
        "abstract_inverted_index",
    ]
)
"""Champs demandés à l'API (`select`)."""


def credential_params() -> dict[str, str]:
    """Identifiants d'une requête OpenAlex : la clé d'API, sinon l'adresse du polite pool, l'une et l'autre facultatives."""
    if api_key := get_openalex_api_key():
        return {"api_key": api_key}
    if email := get_polite_pool_email_optional():
        return {"mailto": email}
    return {}


def auth_params() -> dict[str, str]:
    """Paramètres d'une requête OpenAlex sur les works : identifiants, et inclusion des works hors corpus principal (`include_xpac`)."""
    return {"include_xpac": "true", **credential_params()}


async def fetch_work(
    client: httpx2.AsyncClient, openalex_id: str
) -> LookupOutcome[Mapping[str, JsonValue]]:
    """Un work par son identifiant (`GET /works/{id}`), avec tous ses auteurs. `NOT_FOUND` : work supprimé ou fusionné dans OpenAlex."""
    outcome = await lookup_json_async(
        client,
        "GET",
        f"{API_BASE_URLS['openalex']}/{openalex_id}",
        params={"select": SELECT_FIELDS, **auth_params()},
        timeout=30,
        label=f"OA {openalex_id}",
    )
    if isinstance(outcome, NotFound | Unavailable):
        return outcome
    work = as_mapping(outcome)
    return work if work else UNAVAILABLE


def build_params(
    institution_ids: list[str],
    *,
    years: list[int],
    cursor: str = "*",
    since: str | None = None,
) -> QueryParams:
    """Paramètres d'une requête `/works`.

    `years` borne `publication_year` (une année, ou la plage de la plus petite à la plus grande). `since` (`YYYY-MM-DD`) ajoute `from_updated_date`. Le `lineage:` agrège les institutions par `|` (OR).
    """
    lineage_filter = "|".join(institution_ids or [])
    first, last = min(years), max(years)
    year_filter = (
        f"publication_year:{first}" if first == last else f"publication_year:{first}-{last}"
    )
    filter_str = f"authorships.institutions.lineage:{lineage_filter},{year_filter}"
    if since:
        filter_str += f",from_updated_date:{since}"
    return filter_params(filter_str, cursor=cursor)


def filter_params(filter_str: str, *, cursor: str = "*") -> QueryParams:
    """Paramètres d'une page de `/works` que désigne le filtre `filter_str`."""
    return {
        "filter": filter_str,
        "select": SELECT_FIELDS,
        "per_page": OPENALEX_PER_PAGE,
        "cursor": cursor,
        **auth_params(),
    }


class OpenalexClient:
    """Client de `/works`."""

    def __init__(self, base_url: str) -> None:
        self._url = base_url

    def _get(self, params: QueryParams, label: str) -> Mapping[str, JsonValue]:
        return as_mapping(
            http_request_with_retry("GET", self._url, params=params, timeout=30, label=label)
        )

    def count(
        self, institution_ids: list[str], *, years: list[int], since: str | None = None
    ) -> int:
        """Nombre de works des années `years`, modifiés depuis `since` s'il est donné, lu sur une page d'un seul work réduit à son identifiant."""
        params = {
            **build_params(institution_ids, years=years, since=since),
            "per_page": 1,
            "select": "id",
        }
        data = self._get(params, f"OpenAlex comptage {since or years[0]}")
        return as_int(at_path(data, "meta").get("count")) or 0

    def fetch_page(
        self,
        institution_ids: list[str],
        *,
        years: list[int],
        cursor: str = "*",
        since: str | None = None,
    ) -> Mapping[str, JsonValue]:
        """Une page de works ; `cursor` vaut `"*"` au premier appel, puis le `next_cursor` de la page précédente."""
        params = build_params(institution_ids, years=years, cursor=cursor, since=since)
        return self._get(params, f"OpenAlex {since or years[0]}")

    def fetch_filtered_page(
        self, filter_str: str, cursor: str, label: str
    ) -> Mapping[str, JsonValue]:
        """Une page des works que désigne `filter_str` ; `cursor` vaut `"*"` au premier appel."""
        return self._get(filter_params(filter_str, cursor=cursor), label)


async def search_doi(
    client: httpx2.AsyncClient, doi: str
) -> LookupOutcome[Mapping[str, JsonValue]]:
    """Premier work de `GET /works?filter=doi:{doi}`. `NOT_FOUND` : réponse valide sans résultat, DOI absent d'OpenAlex.

    L'endpoint de liste plafonne les auteurs d'un work, comme le moissonnage.
    """
    outcome = await lookup_json_async(
        client,
        "GET",
        API_BASE_URLS["openalex"],
        params={"filter": f"doi:{doi}", "select": SELECT_FIELDS, **auth_params()},
        timeout=30,
        not_found_statuses=frozenset(),
        label=f"DOI {doi}",
    )
    if isinstance(outcome, NotFound | Unavailable):
        return UNAVAILABLE
    results = as_sequence(as_mapping(outcome).get("results"))
    return as_mapping(results[0]) if results else NOT_FOUND
