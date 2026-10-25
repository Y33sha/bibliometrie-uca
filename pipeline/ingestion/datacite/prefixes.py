"""Client api.datacite.org/prefixes : provider + client (repository) d'un préfixe DOI.

`GET /prefixes/<prefix>?include=clients,providers` (réponse JSON:API) renvoie le provider DataCite (organisation-mère, occupe le slot `publisher_*`) et le client (repository : Zenodo, NAKALA, INRAE, …). Interrogé par le volet publisher de `publishing` quand la RA du préfixe est `'DataCite'`.

Hiérarchie DataCite : `provider → client → prefix → DOI`. Un préfixe est alloué à un seul client. Le `client_symbol` (ex. `cern.zenodo`, `inist.inra`) est l'identifiant stable assigné par DataCite, distinct du nom et persistant au-delà des renommages.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx2

from domain.publications.identifiers import DoiPrefix
from domain.types import JsonValue, as_mapping, as_sequence, as_str, at_path
from pipeline.http.lookup import NOT_FOUND, LookupOutcome, NotFound, Unavailable
from pipeline.ingestion.datacite.api import fetch_prefix


async def fetch_datacite_prefix(
    client: httpx2.AsyncClient, prefix: str
) -> LookupOutcome[tuple[str, str, str]]:
    """Interroge `api.datacite.org/prefixes/<prefix>` pour récupérer provider + client.

    Renvoie `(provider_name, client_name, client_symbol)`. `NOT_FOUND` couvre un préfixe malformé, inconnu de DataCite (404 ou 400), ou une réponse sans provider ni client.
    """
    parsed = DoiPrefix.try_parse(prefix)
    cleaned = str(parsed) if parsed else None
    if not cleaned:
        return NOT_FOUND
    outcome = await fetch_prefix(client, cleaned)
    if isinstance(outcome, NotFound | Unavailable):
        return outcome
    parsed_payload = _parse_datacite_prefix_payload(outcome)
    return NOT_FOUND if parsed_payload is None else parsed_payload


def _parse_datacite_prefix_payload(data: JsonValue) -> tuple[str, str, str] | None:
    """Extrait `(provider_name, client_name, client_symbol)` du payload JSON:API.

    Isolé pour la testabilité : pas de réseau, juste du parsing défensif.
    """
    if not isinstance(data, dict):
        return None
    relationships = at_path(data, "data", "relationships")
    client_refs = as_sequence(at_path(relationships, "clients").get("data"))
    provider_refs = as_sequence(at_path(relationships, "providers").get("data"))
    if not client_refs or not provider_refs:
        return None
    client_symbol = as_str(as_mapping(client_refs[0]).get("id"))
    provider_id = as_str(as_mapping(provider_refs[0]).get("id"))
    if not client_symbol or not provider_id:
        return None
    included_index: dict[tuple[str | None, str | None], Mapping[str, JsonValue]] = {}
    for entry in as_sequence(data.get("included")):
        item = as_mapping(entry)
        included_index[(as_str(item.get("type")), as_str(item.get("id")))] = item
    client_attrs = as_mapping(included_index.get(("clients", client_symbol), {}).get("attributes"))
    provider_attrs = as_mapping(
        included_index.get(("providers", provider_id), {}).get("attributes")
    )
    client_name = as_str(client_attrs.get("name"))
    provider_name = as_str(provider_attrs.get("name"))
    if not client_name:
        return None
    if not provider_name:
        return None
    return provider_name, client_name, client_symbol
