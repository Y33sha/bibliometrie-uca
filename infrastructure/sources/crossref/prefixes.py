"""Client api.crossref.org : éditeur + membre Crossref d'un préfixe DOI.

`GET /prefixes/<prefix>` renvoie le nom du publisher et l'ID membre Crossref d'un préfixe. Interrogé par le volet publisher de `publishers_journals` quand la RA du préfixe est `'Crossref'`. Polite pool via header `User-Agent` (mailto).

Un préfixe reste parfois enregistré au nom d'un compte qui ne dépose plus, pendant qu'un autre compte de la même maison dépose sous ce préfixe. `GET /members/<id>` donne le nombre de DOI déposés par un membre ; à zéro, `GET /works/<doi>` sur un DOI du préfixe rend le membre déposant et son nom, qui font alors foi.
"""

from __future__ import annotations

import logging
import re

from domain.publications.identifiers import DoiPrefix
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.http_retry import http_request_with_retry

logger = logging.getLogger(__name__)

from collections.abc import Mapping

from domain.types import JsonValue, as_mapping

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


def _get_message(url: str, *, user_agent: str, label: str) -> Mapping[str, JsonValue] | None:
    """Corps `message` d'une réponse de l'API Crossref, ou `None` si l'appel échoue."""
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    try:
        data = as_mapping(
            http_request_with_retry(
                "GET", url, headers=headers, timeout=15, max_retries=3, label=label
            )
        )
    except Exception as exc:
        logger.warning("%s : %r", url, exc)
        return None
    msg = data.get("message")
    return as_mapping(msg) if isinstance(msg, dict) else None


def member_deposits(member_id: int, *, user_agent: str) -> int | None:
    """Nombre de DOI déposés par un membre Crossref, ou `None` si l'appel échoue."""
    msg = _get_message(
        f"{API_BASE_URLS['crossref']}/members/{member_id}",
        user_agent=user_agent,
        label=f"membre {member_id}",
    )
    if msg is None:
        return None
    total = as_mapping(msg.get("counts")).get("total-dois")
    return total if isinstance(total, int) else None


def depositing_member(doi: str, *, user_agent: str) -> tuple[str, int] | None:
    """`(nom, membre)` du compte qui a déposé ce DOI, d'après sa notice Crossref."""
    msg = _get_message(
        f"{API_BASE_URLS['crossref']}/works/{doi}", user_agent=user_agent, label=f"notice {doi}"
    )
    if msg is None:
        return None
    member = parse_member_id(msg.get("member"))
    name = msg.get("publisher")
    return (name, member) if member is not None and isinstance(name, str) and name else None


def fetch_crossref_prefix(
    prefix: str, sample_doi: str | None = None, *, user_agent: str
) -> tuple[str, int | None] | None:
    """Interroge `api.crossref.org/prefixes/<prefix>` pour récupérer name + member.

    Renvoie `(publisher_name, member_id)` ou `None` si l'appel échoue ou si `name` est absent. `member_id` peut être `None` si l'API ne le renvoie pas pour ce préfixe.

    Quand le membre enregistré n'a déposé aucun DOI et qu'un DOI du préfixe est fourni, le membre déposant de cette notice prend sa place.
    """
    parsed = DoiPrefix.try_parse(prefix)
    cleaned = str(parsed) if parsed else None
    if not cleaned:
        return None
    msg = _get_message(
        f"{API_BASE_URLS['crossref']}/prefixes/{cleaned}",
        user_agent=user_agent,
        label=f"prefix {cleaned}",
    )
    if msg is None:
        return None
    name = msg.get("name")
    if not isinstance(name, str) or not name:
        return None
    member = parse_member_id(msg.get("member"))
    if member is not None and sample_doi and member_deposits(member, user_agent=user_agent) == 0:
        if depositing := depositing_member(sample_doi, user_agent=user_agent):
            logger.info(
                "Préfixe %s : le membre %d n'a aucun dépôt, le membre déposant %d prend sa place",
                cleaned,
                member,
                depositing[1],
            )
            return depositing
    return name, member
