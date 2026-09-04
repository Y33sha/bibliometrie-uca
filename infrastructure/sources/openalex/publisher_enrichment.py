"""Adapter OpenAlex Publishers → enrichissement du pays des éditeurs (`publishers.country`).

Interroge l'endpoint OpenAlex Publishers par lots d'IDs (filtre à pipe `|`, jusqu'à 50 par requête) pour en tirer le pays du siège. Le HTTP passe par le helper partagé `http_request_with_retry` : retry, backoff et alimentation du circuit-breaker de source (429 / 5xx / réseau) sont gérés là. L'orchestrateur `application` ne reçoit qu'un callable de fetch et ne consulte que l'état du breaker.
"""

from __future__ import annotations

import logging
from typing import NotRequired, TypedDict, cast

from domain.sources.openalex import full_openalex_id, short_openalex_id
from domain.types import as_mapping
from infrastructure.sources.http_retry import http_request_with_retry

logger = logging.getLogger(__name__)

_SELECT = "id,country_codes"


class _OpenAlexPublisher(TypedDict):
    """Sous-ensemble de la payload OpenAlex Publishers consommé ici."""

    id: str
    country_codes: NotRequired[list[str]]


def extract_country(source: _OpenAlexPublisher) -> str | None:
    """Pays d'un éditeur dans la payload OpenAlex Publishers.

    Premier code de `country_codes`, en minuscule (canonique ; OpenAlex renvoie de la majuscule). Un éditeur peut opérer dans plusieurs pays : le premier correspond généralement au siège social. Liste vide ou absente → `None`.
    """
    country_codes = source.get("country_codes") or []
    return country_codes[0].lower() if country_codes else None


def fetch_publishers_batch(
    openalex_ids: list[str],
    *,
    openalex_publishers_api: str,
    api_key: str | None,
    mailto: str,
) -> dict[str, str | None]:
    """Interroge OpenAlex Publishers pour un lot d'IDs.

    Retourne `short_id → pays`, `None` quand OpenAlex n'en donne pas ; un éditeur sur lequel la source ne répond rien est absent du dictionnaire. En cas d'échec (le circuit-breaker de source a enregistré l'échec via `http_request_with_retry`), retourne `{}` — l'appelant consulte l'état du breaker pour décider d'arrêter.
    """
    full_ids = [full_openalex_id(oid) for oid in openalex_ids]
    params: dict[str, str] = {
        "filter": f"ids.openalex:{'|'.join(full_ids)}",
        "per_page": str(len(openalex_ids)),
        "select": _SELECT,
    }
    if api_key:
        params["api_key"] = api_key
    else:
        params["mailto"] = mailto

    try:
        data = as_mapping(
            http_request_with_retry(
                "GET", openalex_publishers_api, params=params, timeout=30, label="publishers batch"
            )
        )
    except Exception as exc:
        logger.warning("OpenAlex publishers batch : %r", exc)
        return {}

    results = cast("list[_OpenAlexPublisher]", data.get("results", []))
    return {short_openalex_id(source["id"]): extract_country(source) for source in results}
