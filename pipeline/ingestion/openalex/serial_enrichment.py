"""Adapter OpenAlex Sources → enrichissement des revues (`serials`).

Interroge l'endpoint OpenAlex Sources par lots d'IDs (filtre à pipe `|`, jusqu'à 50 par requête) pour en tirer le type de source. Le HTTP passe par le helper partagé `http_request_with_retry` : retry, backoff et alimentation du circuit-breaker de source (429 / 5xx / réseau) sont gérés là. L'orchestrateur `application` ne reçoit qu'un callable de fetch et ne consulte que l'état du breaker.
"""

from __future__ import annotations

import logging

import httpx2

from domain.types import as_mapping, as_sequence, as_str
from pipeline.http.circuit_breaker import SourceUnavailableError
from pipeline.http.http_retry import http_request_with_retry
from pipeline.ingestion.openalex.api import credential_params
from pipeline.ingestion.openalex.payload import full_openalex_id, short_openalex_id

logger = logging.getLogger(__name__)

_SELECT = "id,type"


def fetch_sources_batch(
    openalex_ids: list[str],
    *,
    openalex_sources_api: str,
) -> dict[str, str | None]:
    """Interroge OpenAlex Sources pour un lot d'IDs.

    Retourne `short_id → raw_type`. Retourne `{}` si OpenAlex refuse le lot (4xx) ou reste indisponible après les retries ; l'appelant consulte l'état du circuit-breaker pour décider d'arrêter.
    """
    full_ids = [full_openalex_id(oid) for oid in openalex_ids]
    params: dict[str, str] = {
        "filter": f"openalex:{'|'.join(full_ids)}",
        "per_page": str(len(openalex_ids)),
        "select": _SELECT,
        **credential_params(),
    }

    try:
        data = as_mapping(
            http_request_with_retry(
                "GET", openalex_sources_api, params=params, timeout=30, label="sources batch"
            )
        )
    except (httpx2.HTTPStatusError, SourceUnavailableError) as exc:
        logger.warning("OpenAlex sources batch : %r", exc)
        return {}

    result: dict[str, str | None] = {}
    for item in as_sequence(data.get("results")):
        source = as_mapping(item)
        identifier = short_openalex_id(as_str(source.get("id")) or "")
        result[identifier] = as_str(source.get("type"))
    return result
