"""Client api.crossref.org : éditeur + membre Crossref d'un préfixe DOI.

`GET /prefixes/<prefix>` renvoie le nom du publisher et l'ID membre Crossref d'un préfixe. Interrogé par le volet publisher de `publishing` quand la RA du préfixe est `'Crossref'`.

Un préfixe reste parfois enregistré au nom d'un compte qui ne dépose plus, pendant qu'un autre compte dépose sous ce préfixe : un second compte de la même maison, ou celui du groupe qui l'a rachetée. `GET /members/<id>` donne le nom déclaré d'un membre et son nombre de dépôts ; à zéro, `GET /works/<doi>` sur un DOI du préfixe nomme le membre déposant, dont le nom déclaré fait alors foi.
"""

from __future__ import annotations

import logging
import re

import httpx2

from domain.publications.identifiers import DoiPrefix
from domain.types import JsonValue, as_mapping
from pipeline.http.lookup import (
    NOT_FOUND,
    LookupOutcome,
    NotFound,
    Unavailable,
)
from pipeline.ingestion.crossref.api import get_message

logger = logging.getLogger(__name__)

_MEMBER_URL_RE = re.compile(r"/member/(\d+)\b")


def parse_member_id(member: JsonValue) -> int | None:
    """Numéro de membre Crossref, sous les trois formes que prennent les réponses : l'URL `…/member/10` des préfixes, la chaîne `"10"` des enregistrements, ou un entier."""
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


async def member_profile(
    client: httpx2.AsyncClient, member_id: int
) -> LookupOutcome[tuple[str, int]]:
    """`(nom déclaré, nombre de DOI déposés)` d'un membre Crossref."""
    msg = await get_message(client, f"members/{member_id}", label=f"membre {member_id}", timeout=15)
    if isinstance(msg, NotFound | Unavailable):
        return msg
    name = msg.get("primary-name")
    total = as_mapping(msg.get("counts")).get("total-dois")
    return (name, total) if isinstance(name, str) and isinstance(total, int) else NOT_FOUND


async def depositing_member(client: httpx2.AsyncClient, doi: str) -> LookupOutcome[int]:
    """Membre Crossref qui a déposé ce DOI, d'après son enregistrement."""
    msg = await get_message(client, f"works/{doi}", label=f"enregistrement {doi}", timeout=15)
    if isinstance(msg, NotFound | Unavailable):
        return msg
    member = parse_member_id(msg.get("member"))
    return NOT_FOUND if member is None else member


async def fetch_crossref_prefix(
    client: httpx2.AsyncClient, prefix: str, sample_doi: str | None = None
) -> LookupOutcome[tuple[str, int | None]]:
    """Interroge `api.crossref.org/prefixes/<prefix>` pour récupérer name + member.

    Renvoie `(publisher_name, member_id)`. `NOT_FOUND` couvre un préfixe malformé, inconnu de Crossref ou sans nom. `member_id` peut être `None` si l'API ne le renvoie pas pour ce préfixe.

    Quand le membre enregistré n'a déposé aucun DOI et qu'un DOI du préfixe est fourni, le membre déposant de cet enregistrement prend sa place. Une requête de cette vérification qui échoue rend le préfixe entier `UNAVAILABLE`.
    """
    parsed = DoiPrefix.try_parse(prefix)
    cleaned = str(parsed) if parsed else None
    if not cleaned:
        return NOT_FOUND
    msg = await get_message(client, f"prefixes/{cleaned}", label=f"prefix {cleaned}", timeout=15)
    if isinstance(msg, NotFound | Unavailable):
        return msg
    name = msg.get("name")
    if not isinstance(name, str) or not name:
        return NOT_FOUND
    member = parse_member_id(msg.get("member"))
    registered = (name, member)
    if member is None or not sample_doi:
        return registered
    profile = await member_profile(client, member)
    if isinstance(profile, Unavailable):
        return profile
    if isinstance(profile, NotFound) or profile[1] > 0:
        return registered
    depositing = await depositing_member(client, sample_doi)
    if isinstance(depositing, Unavailable):
        return depositing
    if isinstance(depositing, NotFound) or depositing == member:
        return registered
    # Le nom vient du membre déposant, et non de l'enregistrement : celui-ci donne l'imprint, qui varie d'un
    # dépôt à l'autre sous un même compte.
    deposited_by = await member_profile(client, depositing)
    if isinstance(deposited_by, Unavailable):
        return deposited_by
    if isinstance(deposited_by, NotFound):
        return registered
    logger.info(
        "Préfixe %s : le membre %d n'a aucun dépôt, le membre déposant %d « %s » prend sa place",
        cleaned,
        member,
        depositing,
        deposited_by[0],
    )
    return deposited_by[0], depositing
