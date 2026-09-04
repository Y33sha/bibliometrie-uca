"""Client api.crossref.org/prefixes : éditeur + member Crossref d'un préfixe DOI.

`GET /prefixes/<prefix>` renvoie le nom du publisher et l'ID member Crossref d'un préfixe. Interrogé par le volet publisher de `publishers_journals` quand la RA du préfixe est `'Crossref'`. Polite pool via header `User-Agent` (mailto).
"""

from __future__ import annotations

import logging
import re

from domain.publications.identifiers import clean_doi_prefix
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.http_retry import http_request_with_retry

logger = logging.getLogger(__name__)

from domain.types import JsonValue

_MEMBER_URL_RE = re.compile(r"/member/(\d+)\b")


def parse_member_id(member: JsonValue) -> int | None:
    """Numéro de membre Crossref, extrait de la forme `…/member/10` qu'il prend dans les réponses. Accepte aussi un int brut."""
    if member is None:
        return None
    if isinstance(member, int):
        return member
    if isinstance(member, str):
        m = _MEMBER_URL_RE.search(member)
        if m:
            return int(m.group(1))
    return None


def fetch_crossref_prefix(prefix: str, *, user_agent: str) -> tuple[str, int | None] | None:
    """Interroge `api.crossref.org/prefixes/<prefix>` pour récupérer name + member.

    Renvoie `(publisher_name, member_id)` ou `None` si l'appel échoue ou si `name` est absent. `member_id` peut être `None` si l'API ne le renvoie pas pour ce préfixe.
    """
    cleaned = clean_doi_prefix(prefix)
    if not cleaned:
        return None
    url = f"{API_BASE_URLS['crossref']}/prefixes/{cleaned}"
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    try:
        data = http_request_with_retry(
            "GET", url, headers=headers, timeout=15, max_retries=3, label=f"prefix {cleaned}"
        )
    except Exception as exc:
        logger.warning("api.crossref.org/prefixes/%s : %r", cleaned, exc)
        return None
    msg = data.get("message") if isinstance(data, dict) else None
    if not isinstance(msg, dict):
        return None
    name = msg.get("name")
    if not isinstance(name, str) or not name:
        return None
    return name, parse_member_id(msg.get("member"))
