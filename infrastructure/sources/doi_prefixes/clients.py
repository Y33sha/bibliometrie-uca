"""Clients HTTP pour la résolution préfixe DOI → RA + éditeur Crossref / repository DataCite.

Trois endpoints, appelés depuis la phase pipeline `resolve_doi_prefixes` :

- `doi.org/ra/<doi>` : Registration Agency d'un DOI donné. Une RA est permanente à l'échelle d'un préfixe (un préfixe = un registrant = une RA), donc un seul appel par préfixe suffit côté pipeline — mais en pratique on essaie plusieurs DOI samples par préfixe pour se prémunir d'un DOI erroné dans le staging.
- `api.crossref.org/prefixes/<prefix>` : nom du publisher + ID member Crossref. Appelé uniquement quand la RA résolue précédemment est `'Crossref'`.
- `api.datacite.org/prefixes/<prefix>?include=clients,providers` : nom du provider DataCite (= organisation-mère, occupe le slot `publisher_*`) + nom et symbole du client DataCite (= repository : Zenodo, NAKALA, INRAE, …). Appelé uniquement quand la RA est `'DataCite'`. Spike Phase 0 a vérifié 1 préfixe = 1 client sur 105/105.

Polite pool via header `User-Agent` (mailto). Pas de polite pool documenté côté doi.org ni côté DataCite, on l'inclut par cohérence.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any

from domain.publications.identifiers import clean_doi, clean_doi_prefix
from infrastructure.sources.http_retry import http_request_with_retry

logger = logging.getLogger(__name__)

DOI_RA_BASE_URL = "https://doi.org/ra"
CROSSREF_PREFIX_BASE_URL = "https://api.crossref.org/prefixes"
DATACITE_PREFIX_BASE_URL = "https://api.datacite.org/prefixes"

# Sentinelle renvoyée par doi.org/ra quand le DOI fourni n'existe pas.
_DOI_NOT_FOUND = "DOI Not Found"
_MEMBER_URL_RE = re.compile(r"/member/(\d+)\b")


def parse_member_id(member: Any) -> int | None:
    """`https://id.crossref.org/member/10` → `10`. Accepte aussi un int brut."""
    if member is None:
        return None
    if isinstance(member, int):
        return member
    if isinstance(member, str):
        m = _MEMBER_URL_RE.search(member)
        if m:
            return int(m.group(1))
    return None


def resolve_ra(doi: str, *, user_agent: str) -> str | None:
    """Interroge `doi.org/ra` pour récupérer la Registration Agency d'un DOI.

    Renvoie le nom de la RA (`'Crossref'`, `'DataCite'`, `'mEDRA'`,
    `'unknown'`, …) ou `None` si la résolution échoue (DOI inconnu,
    erreur réseau/HTTP). Le caller doit retenter avec un autre DOI du
    même préfixe si `None`.

    Note : `'unknown'` est une valeur **valide** renvoyée par doi.org
    pour un préfixe enregistré chez une RA hors du set principal — c'est
    distinct de la non-résolution (qui renvoie ici `None`).
    """
    cleaned = clean_doi(doi)
    if not cleaned:
        return None
    url = f"{DOI_RA_BASE_URL}/{urllib.parse.quote(cleaned, safe='')}"
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    try:
        data = http_request_with_retry(
            "GET", url, headers=headers, timeout=15, max_retries=3, label=f"DOI {doi}"
        )
    except Exception as exc:
        logger.warning(f"doi.org/ra {doi} : {exc!r}")
        return None
    if not isinstance(data, list) or not data:
        return None
    ra = data[0].get("RA") if isinstance(data[0], dict) else None
    if not isinstance(ra, str) or not ra or ra == _DOI_NOT_FOUND:
        return None
    return ra


def fetch_crossref_prefix(prefix: str, *, user_agent: str) -> tuple[str, int | None] | None:
    """Interroge `api.crossref.org/prefixes/<prefix>` pour récupérer name + member.

    Renvoie `(publisher_name, member_id)` ou `None` si l'appel échoue
    ou si `name` est absent. `member_id` peut être `None` si l'API ne le
    renvoie pas pour ce préfixe.
    """
    prefix = clean_doi_prefix(prefix)
    if not prefix:
        return None
    url = f"{CROSSREF_PREFIX_BASE_URL}/{prefix}"
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    try:
        data = http_request_with_retry(
            "GET", url, headers=headers, timeout=15, max_retries=3, label=f"prefix {prefix}"
        )
    except Exception as exc:
        logger.warning(f"api.crossref.org/prefixes/{prefix} : {exc!r}")
        return None
    msg = data.get("message") if isinstance(data, dict) else None
    if not isinstance(msg, dict):
        return None
    name = msg.get("name")
    if not isinstance(name, str) or not name:
        return None
    return name, parse_member_id(msg.get("member"))


def fetch_datacite_prefix(prefix: str, *, user_agent: str) -> tuple[str, str, str] | None:
    """Interroge `api.datacite.org/prefixes/<prefix>` pour récupérer provider + client.

    Endpoint `GET /prefixes/{p}?include=clients,providers`, réponse JSON:API. Renvoie `(provider_name, client_name, client_symbol)` ou `None` si l'appel échoue ou si la structure attendue est incomplète.

    Hiérarchie DataCite : `provider → client → prefix → DOI`. Un préfixe est alloué à un seul client (validé Phase 0 sur 105/105 prefixes UCA). Le `client_symbol` (ex. `cern.zenodo`, `inist.inra`) est l'identifiant stable assigné par DataCite, distinct du nom et persistant au-delà des renommages.
    """
    prefix = clean_doi_prefix(prefix)
    if not prefix:
        return None
    url = f"{DATACITE_PREFIX_BASE_URL}/{prefix}"
    headers = {"User-Agent": user_agent, "Accept": "application/vnd.api+json"}
    try:
        data = http_request_with_retry(
            "GET",
            url,
            params={"include": "clients,providers"},
            headers=headers,
            timeout=15,
            max_retries=3,
            label=f"datacite prefix {prefix}",
        )
    except Exception as exc:
        logger.warning(f"api.datacite.org/prefixes/{prefix} : {exc!r}")
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


def build_user_agent(email: str) -> str:
    """Construit le `User-Agent` pour les appels doi.org / api.crossref.org / api.datacite.org."""
    return f"BibliometrieUCA-pipeline/1.0 (mailto:{email})"
