"""Client doi.org/ra : agence d'enregistrement des préfixes DOI.

`doi.org/ra/<p1>,<p2>,…` renvoie l'agence d'enregistrement de chaque préfixe (`Crossref`, `DataCite`, `mEDRA`…), ou le statut `DOI does not exist` pour un préfixe inconnu. Une agence vaut pour tous les DOI d'un préfixe. Interrogé par la phase `resolve_ra`. Polite pool via header `User-Agent` (mailto).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Sequence

import httpx2

from domain.types import as_mapping, as_sequence, as_str
from infrastructure.sources.api_params import API_BASE_URLS, DOI_ORG_RA_BATCH
from infrastructure.sources.http_retry import http_request_with_retry

logger = logging.getLogger(__name__)


def fetch_registration_agencies(
    prefixes: Sequence[str], *, user_agent: str
) -> Iterator[tuple[str, str | None]]:
    """Agence d'enregistrement de chaque préfixe DOI, par lots de `DOI_ORG_RA_BATCH` préfixes.

    Rend `(préfixe, agence)`, avec l'agence `None` quand doi.org ne connaît pas le préfixe. Les préfixes d'un lot dont la requête échoue sont absents du résultat. L'indisponibilité de doi.org sous circuit-breaker lève `SourceUnavailableError`.
    """
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    for i in range(0, len(prefixes), DOI_ORG_RA_BATCH):
        batch = prefixes[i : i + DOI_ORG_RA_BATCH]
        url = f"{API_BASE_URLS['doi_org']}/{','.join(batch)}"
        try:
            data = http_request_with_retry(
                "GET", url, headers=headers, timeout=15, label=f"lot de {len(batch)} préfixes"
            )
        except (httpx2.HTTPStatusError, json.JSONDecodeError) as exc:
            logger.warning("doi.org/ra, lot de %d préfixes : %r", len(batch), exc)
            continue
        asked = set(batch)
        for entry in as_sequence(data):
            answer = as_mapping(entry)
            prefix = as_str(answer.get("DOI"))
            if prefix in asked:
                yield prefix, as_str(answer.get("RA")) or None
