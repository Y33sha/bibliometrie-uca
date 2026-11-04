"""Client OpenAlex des sources et des listes de revues.

`/sources` reçoit des lots d'ISSN ou d'identifiants, en filtre à `|` de `SOURCES_BATCH` valeurs au plus. Les requêtes passent par `http_request_with_retry` : nouvelles tentatives, backoff et circuit-breaker de la source. La sous-étape cliente reçoit seulement les fonctions de requête, et consulte l'état du circuit-breaker.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Literal

import httpx2

from domain.documents.identifiers import ISSN
from domain.sources.openalex import OpenAlexSource, OpenAlexSourceList
from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str
from pipeline.http.circuit_breaker import SourceUnavailableError
from pipeline.http.http_retry import http_request_with_retry
from pipeline.ingestion.openalex.api import credential_params
from pipeline.ingestion.openalex.payload import full_openalex_id, short_openalex_id

logger = logging.getLogger(__name__)

SOURCES_BATCH = 100
"""Valeurs d'un filtre à `|`, plafond d'OpenAlex."""

_PER_PAGE = 200
_SELECT = "id,issn,type,listed_in,works_count"

type SourceFilter = Literal["issn", "openalex"]
"""Filtre de `/sources` : par ISSN, ou par identifiant OpenAlex."""


def fetch_sources(
    key: SourceFilter, values: Sequence[str], *, sources_api: str
) -> list[OpenAlexSource] | None:
    """Renvoie les sources OpenAlex d'un lot d'ISSN ou d'identifiants courts, ou `None` si la requête échoue : refus (4xx), ou absence de réponse après les nouvelles tentatives."""
    terms = [full_openalex_id(v) for v in values] if key == "openalex" else list(values)
    data = _get(
        sources_api,
        {
            "filter": f"{key}:{'|'.join(terms)}",
            "per_page": str(_PER_PAGE),
            "select": _SELECT,
            **credential_params(),
        },
        label="sources",
    )
    if data is None:
        return None
    return [s for item in as_sequence(data.get("results")) if (s := parse_source(as_mapping(item)))]


def fetch_source_lists(*, source_lists_api: str) -> list[OpenAlexSourceList] | None:
    """Renvoie les listes de revues d'OpenAlex, ou `None` si la requête échoue."""
    data = _get(
        source_lists_api,
        {"per_page": str(_PER_PAGE), **credential_params()},
        label="source-lists",
    )
    if data is None:
        return None
    return [
        s for item in as_sequence(data.get("results")) if (s := parse_source_list(as_mapping(item)))
    ]


def parse_source(item: Mapping[str, JsonValue]) -> OpenAlexSource | None:
    """Renvoie la source décrite par un élément de réponse de `/sources`, ou `None` sans identifiant."""
    identifier = as_str(item.get("id"))
    if not identifier:
        return None
    issns = (
        str(issn)
        for value in as_sequence(item.get("issn"))
        if (issn := ISSN.try_parse(as_str(value)))
    )
    return OpenAlexSource(
        id=short_openalex_id(identifier),
        issns=tuple(dict.fromkeys(issns)),
        type=as_str(item.get("type")),
        listed_in=tuple(
            code for value in as_sequence(item.get("listed_in")) if (code := as_str(value))
        ),
        works_count=as_int(item.get("works_count")) or 0,
    )


def parse_source_list(item: Mapping[str, JsonValue]) -> OpenAlexSourceList | None:
    """Renvoie la liste décrite par un élément de réponse de `/source-lists`, ou `None` sans identifiant. Le code est le dernier segment de l'identifiant."""
    identifier = as_str(item.get("id"))
    if not identifier:
        return None
    return OpenAlexSourceList(
        code=identifier.rsplit("/", 1)[-1],
        maintainer=as_str(item.get("maintainer")),
        url=as_str(item.get("url")),
        edition=_date(as_str(item.get("list_version"))),
    )


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _get(url: str, params: Mapping[str, str], *, label: str) -> Mapping[str, JsonValue] | None:
    try:
        return as_mapping(
            http_request_with_retry("GET", url, params=dict(params), timeout=30, label=label)
        )
    except (httpx2.HTTPStatusError, SourceUnavailableError) as exc:
        logger.warning("OpenAlex %s : %r", label, exc)
        return None
