"""Accès à l'API OpenAlex : identifiants des requêtes, lecture d'un work par son identifiant."""

from __future__ import annotations

from collections.abc import Mapping

import httpx2

from domain.types import JsonValue, as_mapping
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.config import get_openalex_api_key, get_polite_pool_email_optional
from infrastructure.sources.http_retry import lookup_json_async
from infrastructure.sources.lookup import UNAVAILABLE, LookupOutcome, NotFound, Unavailable
from pipeline.sources.openalex.fields import SELECT_FIELDS


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
