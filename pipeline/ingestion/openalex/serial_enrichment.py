"""Client OpenAlex des sources : type de source des revues.

La requête `/sources` reçoit des lots d'identifiants (filtre à `|`, 50 au plus par requête). Les requêtes passent par `http_request_with_retry` : nouvelles tentatives, backoff et circuit-breaker de la source. La sous-étape cliente reçoit seulement la fonction de requête, et consulte l'état du circuit-breaker.
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
    """Renvoie le type brut de chaque source d'un lot, par identifiant court.

    Un lot refusé (4xx), ou sans réponse après les nouvelles tentatives, renvoie `{}` ; l'appelant consulte le circuit-breaker pour s'arrêter.
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
