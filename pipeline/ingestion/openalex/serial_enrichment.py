"""Adapter OpenAlex Sources → enrichissement des revues (`serials`).

Interroge l'endpoint OpenAlex Sources par lots d'IDs (filtre à pipe `|`, jusqu'à 50 par requête) pour en tirer l'APC et le type de source. Le HTTP passe par le helper partagé `http_request_with_retry` : retry, backoff et alimentation du circuit-breaker de source (429 / 5xx / réseau) sont gérés là. L'orchestrateur `application` ne reçoit qu'un callable de fetch et ne consulte que l'état du breaker.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

import httpx2

from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.http.circuit_breaker import SourceUnavailableError
from pipeline.http.http_retry import http_request_with_retry
from pipeline.ingestion.openalex.api import credential_params
from pipeline.ingestion.openalex.payload import full_openalex_id, short_openalex_id

logger = logging.getLogger(__name__)

_SELECT = "id,apc_usd,apc_prices,type"


def extract_apc(source: Mapping[str, JsonValue]) -> tuple[float, str] | None:
    """Montant et devise APC d'un objet source OpenAlex, ou `None` quand OpenAlex ne donne aucun montant.

    Priorité, parmi les prix renseignés : EUR dans `apc_prices` > première devise disponible > `apc_usd` en USD.
    """
    prices = [
        (amount, as_str(entry.get("currency")) or "USD")
        for price_item in as_sequence(source.get("apc_prices"))
        if (amount := _amount((entry := as_mapping(price_item)).get("price"))) is not None
    ]
    for amount, currency in prices:
        if currency == "EUR":
            return amount, currency
    if prices:
        return prices[0]
    if (apc_usd := _amount(source.get("apc_usd"))) is not None:
        return apc_usd, "USD"
    return None


def _amount(value: JsonValue) -> float | None:
    """Montant de `value` : l'API rend un entier ou un décimal selon la devise."""
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, int | float) else None


def fetch_sources_batch(
    openalex_ids: list[str],
    *,
    openalex_sources_api: str,
) -> dict[str, tuple[float | None, str | None, str | None]]:
    """Interroge OpenAlex Sources pour un lot d'IDs.

    Retourne `short_id → (apc_amount, apc_currency, raw_type)`, montant et devise à `None` quand OpenAlex ne donne pas d'APC. Retourne `{}` si OpenAlex refuse le lot (4xx) ou reste indisponible après les retries ; l'appelant consulte l'état du circuit-breaker pour décider d'arrêter.
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

    result: dict[str, tuple[float | None, str | None, str | None]] = {}
    for price_item in as_sequence(data.get("results")):
        source = as_mapping(price_item)
        apc_amount, apc_currency = extract_apc(source) or (None, None)
        identifier = short_openalex_id(as_str(source.get("id")) or "")
        result[identifier] = (apc_amount, apc_currency, as_str(source.get("type")))
    return result
