"""Client API Crossref Members — `GET /members/{id}`.

Consommé par le sub-step pipeline `enrich_publishers_from_crossref_members`
(fallback `country` quand OpenAlex Publishers n'a pas eu de match) et
par l'audit `audit_crossref_member_countries`.

Polite pool via header `User-Agent` (mailto), cohérent avec les autres
clients Crossref du projet (`doi_prefixes/clients.py`,
`crossref/fetch_missing_doi.py`).
"""

from __future__ import annotations

import logging
from typing import Any

import requests

CROSSREF_MEMBER_URL = "https://api.crossref.org/members/{id}"


def fetch_crossref_member(
    member_id: int,
    *,
    user_agent: str,
    logger: logging.Logger,
    timeout: float = 15.0,
) -> dict[str, Any] | None:
    """GET sur `api.crossref.org/members/{id}`.

    Retourne le bloc `message` (= record du member) ou ``None`` sur 404
    / erreur réseau. Pas de retry élaboré ; les consommateurs tolèrent
    un fetch raté.
    """
    try:
        resp = requests.get(
            CROSSREF_MEMBER_URL.format(id=member_id),
            headers={"User-Agent": user_agent},
            timeout=timeout,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        body = resp.json()
        msg = body.get("message") if isinstance(body, dict) else None
        return msg if isinstance(msg, dict) else None
    except requests.RequestException as e:
        logger.warning("Crossref member fetch failed for %d : %s", member_id, e)
        return None
