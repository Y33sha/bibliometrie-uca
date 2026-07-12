"""Adapter OpenAlex Sources → enrichissement des revues (`journals`).

Interroge l'endpoint OpenAlex Sources par lots d'IDs (filtre à pipe `|`, jusqu'à 50 par requête) pour en tirer l'APC et le type de source. Le HTTP passe par le helper partagé `http_request_with_retry` : retry, backoff et alimentation du circuit-breaker de source (429 / 5xx / réseau) sont gérés là. L'orchestrateur `application` ne reçoit qu'un callable de fetch et ne consulte que l'état du breaker.
"""

from __future__ import annotations

import logging

from domain.sources.openalex import full_openalex_id, short_openalex_id
from infrastructure.sources.http_retry import http_request_with_retry

logger = logging.getLogger(__name__)

_SELECT = "id,apc_usd,apc_prices,type"


def extract_apc(source: dict) -> tuple[float | None, str]:
    """Montant et devise APC d'un objet source OpenAlex.

    Priorité : EUR dans `apc_prices` > première devise disponible > `apc_usd` en USD.
    """
    apc_prices = source.get("apc_prices") or []
    for entry in apc_prices:
        if entry.get("currency") == "EUR":
            return entry["price"], "EUR"
    if apc_prices:
        entry = apc_prices[0]
        return entry["price"], entry.get("currency", "USD")
    apc_usd = source.get("apc_usd")
    if apc_usd is not None:
        return apc_usd, "USD"
    return None, "EUR"


def fetch_sources_batch(
    openalex_ids: list[str],
    *,
    openalex_sources_api: str,
    api_key: str | None,
    mailto: str,
) -> dict[str, tuple[float | None, str, str | None]]:
    """Interroge OpenAlex Sources pour un lot d'IDs.

    Retourne `short_id → (apc_amount, apc_currency, raw_type)`. En cas d'échec (le
    circuit-breaker de source a enregistré l'échec via `http_request_with_retry`),
    retourne `{}` — l'appelant consulte l'état du breaker pour décider d'arrêter.
    """
    full_ids = [full_openalex_id(oid) for oid in openalex_ids]
    params: dict[str, str] = {
        "filter": f"openalex:{'|'.join(full_ids)}",
        "per_page": str(len(openalex_ids)),
        "select": _SELECT,
    }
    if api_key:
        params["api_key"] = api_key
    else:
        params["mailto"] = mailto

    try:
        data = http_request_with_retry(
            "GET", openalex_sources_api, params=params, timeout=30, label="sources batch"
        )
    except Exception as exc:
        logger.warning("OpenAlex sources batch : %r", exc)
        return {}

    result: dict[str, tuple[float | None, str, str | None]] = {}
    for source in data.get("results", []):
        apc_amount, apc_currency = extract_apc(source)
        result[short_openalex_id(source["id"])] = (apc_amount, apc_currency, source.get("type"))
    return result
