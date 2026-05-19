"""Clients HTTP pour la résolution préfixe DOI → RA + éditeur Crossref.

Deux endpoints, appelés depuis la phase pipeline `resolve_doi_prefixes` :

- `doi.org/ra/<doi>` : Registration Agency d'un DOI donné. Une RA est
  permanente à l'échelle d'un préfixe (un préfixe = un registrant = une
  RA), donc un seul appel par préfixe suffit côté pipeline — mais en
  pratique on essaie plusieurs DOI samples par préfixe pour se prémunir
  d'un DOI erroné dans le staging.
- `api.crossref.org/prefixes/<prefix>` : nom du publisher + ID member
  Crossref. Appelé uniquement quand la RA résolue précédemment est
  `'Crossref'`.

Polite pool via header `User-Agent` (mailto). Pas de polite pool
documenté côté doi.org, on l'inclut par cohérence.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any

from infrastructure.sources.http_retry import http_request_with_retry

logger = logging.getLogger(__name__)

DOI_RA_BASE_URL = "https://doi.org/ra"
CROSSREF_PREFIX_BASE_URL = "https://api.crossref.org/prefixes"

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
    url = f"{DOI_RA_BASE_URL}/{urllib.parse.quote(doi, safe='')}"
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


def build_user_agent(email: str) -> str:
    """Construit le `User-Agent` pour les appels doi.org / api.crossref.org."""
    return f"BibliometrieUCA-pipeline/1.0 (mailto:{email})"
