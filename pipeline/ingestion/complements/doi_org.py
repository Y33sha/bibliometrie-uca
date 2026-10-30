"""Client doi.org : agence d'enregistrement des préfixes DOI, et existence d'un DOI.

`doi.org/ra/<p1>,<p2>,…` renvoie l'agence d'enregistrement de chaque préfixe (`Crossref`, `DataCite`, `mEDRA`…), ou le statut `DOI does not exist` pour un préfixe inconnu. Une agence vaut pour tous les DOI d'un préfixe. Interrogé par la phase `resolve_ra`.

`doi.org/api/handles/<doi>` répond 404 pour un DOI inconnu du registre. Interrogé par la phase `fetch_missing` pour un DOI absent de son agence d'enregistrement. Les requêtes s'identifient par l'adresse polite pool, dans le `User-Agent`.
"""

from __future__ import annotations

import logging
import urllib.parse
from collections.abc import Iterator, Sequence

import httpx2

from domain.types import as_mapping, as_sequence, as_str
from pipeline.http.http_retry import http_request_with_retry, lookup_json_async
from pipeline.http.lookup import NotFound, Unavailable
from pipeline.ingestion.api_params import API_BASE_URLS, DOI_ORG_RA_BATCH

logger = logging.getLogger(__name__)


def fetch_registration_agencies(
    prefixes: Sequence[str], *, user_agent: str
) -> Iterator[tuple[str, str | None]]:
    """Renvoie l'agence d'enregistrement de chaque préfixe DOI, interrogée par lots de `DOI_ORG_RA_BATCH` préfixes.

    Renvoie des couples `(préfixe, agence)`, avec l'agence `None` pour un préfixe inconnu de doi.org. Les préfixes d'un lot refusé par doi.org (4xx) sont absents du résultat. L'indisponibilité de doi.org lève `SourceUnavailableError`.
    """
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    for i in range(0, len(prefixes), DOI_ORG_RA_BATCH):
        batch = prefixes[i : i + DOI_ORG_RA_BATCH]
        url = f"{API_BASE_URLS['doi_org']}/{','.join(batch)}"
        try:
            data = http_request_with_retry(
                "GET", url, headers=headers, timeout=15, label=f"lot de {len(batch)} préfixes"
            )
        except httpx2.HTTPStatusError as exc:
            logger.warning("doi.org/ra, lot de %d préfixes : %r", len(batch), exc)
            continue
        asked = set(batch)
        for entry in as_sequence(data):
            answer = as_mapping(entry)
            prefix = as_str(answer.get("DOI"))
            if prefix in asked:
                yield prefix, as_str(answer.get("RA")) or None


async def doi_existence(
    client: httpx2.AsyncClient, dois: Sequence[str], *, user_agent: str
) -> tuple[list[str], list[str]]:
    """Répartit des DOI entre DOI connus et inconnus de doi.org. Un DOI sans réponse concluante reste hors des deux listes."""
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    known: list[str] = []
    unknown: list[str] = []
    for doi in dois:
        url = f"{API_BASE_URLS['doi_org_handles']}/{urllib.parse.quote(doi, safe='/()')}"
        outcome = await lookup_json_async(
            client, "GET", url, headers=headers, timeout=15, label=f"DOI {doi}"
        )
        if isinstance(outcome, NotFound):
            unknown.append(doi)
        elif not isinstance(outcome, Unavailable):
            known.append(doi)
    return known, unknown
