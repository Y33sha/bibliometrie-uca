"""Client api.crossref.org : éditeur + membre Crossref d'un préfixe DOI.

`GET /prefixes/<prefix>` renvoie le nom du publisher et l'ID membre Crossref d'un préfixe. Interrogé par le volet publisher de `publishers_journals` quand la RA du préfixe est `'Crossref'`. Polite pool via header `User-Agent` (mailto).

Un préfixe reste parfois enregistré au nom d'un compte qui ne dépose plus, pendant qu'un autre compte dépose sous ce préfixe : un second compte de la même maison, ou celui du groupe qui l'a rachetée. `GET /members/<id>` donne le nom déclaré d'un membre et son nombre de dépôts ; à zéro, `GET /works/<doi>` sur un DOI du préfixe nomme le membre déposant, dont le nom déclaré fait alors foi.
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
    """Numéro de membre Crossref, sous les trois formes que prennent les réponses : l'URL `…/member/10` des préfixes, la chaîne `"10"` des notices, ou un entier."""
    if isinstance(member, bool) or member is None:
        return None
    if isinstance(member, int):
        return member
    if isinstance(member, str):
        if m := _MEMBER_URL_RE.search(member):
            return int(m.group(1))
        if member.isdigit():
            return int(member)
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


def member_profile(member_id: int, *, user_agent: str) -> tuple[str, int] | None:
    """`(nom déclaré, nombre de DOI déposés)` d'un membre Crossref, ou `None` si l'appel échoue."""
    msg = _get_message(
        f"{API_BASE_URLS['crossref']}/members/{member_id}",
        user_agent=user_agent,
        label=f"membre {member_id}",
    )
    if msg is None:
        return None
    name = msg.get("primary-name")
    total = as_mapping(msg.get("counts")).get("total-dois")
    return (name, total) if isinstance(name, str) and isinstance(total, int) else None


def depositing_member(doi: str, *, user_agent: str) -> int | None:
    """Membre Crossref qui a déposé ce DOI, d'après sa notice."""
    msg = _get_message(
        f"{API_BASE_URLS['crossref']}/works/{doi}", user_agent=user_agent, label=f"notice {doi}"
    )
    return parse_member_id(msg.get("member")) if msg is not None else None


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
    if member is None or not sample_doi:
        return name, member
    profile = member_profile(member, user_agent=user_agent)
    if profile is None or profile[1] > 0:
        return name, member
    depositing = depositing_member(sample_doi, user_agent=user_agent)
    if depositing is None or depositing == member:
        return name, member
    # Le nom vient du membre déposant, non de la notice : celle-ci porte l'imprint, qui varie d'un
    # dépôt à l'autre sous un même compte.
    deposited_by = member_profile(depositing, user_agent=user_agent)
    if deposited_by is None:
        return name, member
    logger.info(
        "Préfixe %s : le membre %d n'a aucun dépôt, le membre déposant %d « %s » prend sa place",
        cleaned,
        member,
        depositing,
        deposited_by[0],
    )
    return deposited_by[0], depositing
