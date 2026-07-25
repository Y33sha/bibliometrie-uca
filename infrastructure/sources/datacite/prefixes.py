"""Client api.datacite.org/prefixes : provider + client (repository) d'un préfixe DOI.

`GET /prefixes/<prefix>?include=clients,providers` (réponse JSON:API) renvoie le provider DataCite (organisation-mère, occupe le slot `publisher_*`) et le client (repository : Zenodo, NAKALA, INRAE, …). Interrogé par le volet publisher de `publishers_journals` quand la RA du préfixe est `'DataCite'`. Polite pool via header `User-Agent` (mailto).

Hiérarchie DataCite : `provider → client → prefix → DOI`. Un préfixe est alloué à un seul client. Le `client_symbol` (ex. `cern.zenodo`, `inist.inra`) est l'identifiant stable assigné par DataCite, distinct du nom et persistant au-delà des renommages.
"""

from __future__ import annotations

import logging
from typing import Any

from domain.publications.identifiers import clean_doi_prefix
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.http_retry import http_request_with_retry

logger = logging.getLogger(__name__)


def fetch_datacite_prefix(prefix: str, *, user_agent: str) -> tuple[str, str, str] | None:
    """Interroge `api.datacite.org/prefixes/<prefix>` pour récupérer provider + client.

    Renvoie `(provider_name, client_name, client_symbol)` ou `None` si l'appel échoue ou si la structure attendue est incomplète.
    """
    cleaned = clean_doi_prefix(prefix)
    if not cleaned:
        return None
    url = f"{API_BASE_URLS['datacite']}/prefixes/{cleaned}"
    headers = {"User-Agent": user_agent, "Accept": "application/vnd.api+json"}
    try:
        data = http_request_with_retry(
            "GET",
            url,
            params={"include": "clients,providers"},
            headers=headers,
            timeout=15,
            max_retries=3,
            label=f"datacite prefix {cleaned}",
        )
    except Exception as exc:
        logger.warning(f"api.datacite.org/prefixes/{cleaned} : {exc!r}")
        return None
    return _parse_datacite_prefix_payload(data)


def _parse_datacite_prefix_payload(data: Any) -> tuple[str, str, str] | None:
    """Extrait `(provider_name, client_name, client_symbol)` du payload JSON:API.

    Isolé pour la testabilité : pas de réseau, juste du parsing défensif.
    """
    if not isinstance(data, dict):
        return None
    relationships = (data.get("data") or {}).get("relationships") or {}
    client_refs = (relationships.get("clients") or {}).get("data") or []
    provider_refs = (relationships.get("providers") or {}).get("data") or []
    if not client_refs or not provider_refs:
        return None
    client_symbol = client_refs[0].get("id") if isinstance(client_refs[0], dict) else None
    provider_id = provider_refs[0].get("id") if isinstance(provider_refs[0], dict) else None
    if not client_symbol or not provider_id:
        return None
    included_index: dict[tuple[str | None, str | None], dict] = {}
    for item in data.get("included") or []:
        if isinstance(item, dict):
            included_index[(item.get("type"), item.get("id"))] = item
    client_attrs = (included_index.get(("clients", client_symbol)) or {}).get("attributes") or {}
    provider_attrs = (included_index.get(("providers", provider_id)) or {}).get("attributes") or {}
    client_name = client_attrs.get("name")
    provider_name = provider_attrs.get("name")
    if not isinstance(client_name, str) or not client_name:
        return None
    if not isinstance(provider_name, str) or not provider_name:
        return None
    return provider_name, client_name, client_symbol
