"""Source Crossref : recherche par DOI et par personne, nouvelle lecture des documents."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING

from domain.sources.registry import Source
from domain.types import JsonValue
from pipeline.ingestion.common.adapter import RecordIdentity, SourceAdapter

if TYPE_CHECKING:
    import httpx2
    from sqlalchemy import Connection

    from pipeline.ingestion.common.doi_search import DoiSearch
    from pipeline.ingestion.common.harvester import Harvester
    from pipeline.ingestion.common.normalizer import SourceNormalizer
    from pipeline.ingestion.common.stale_refetch import FetchOutcome
    from pipeline.ingestion.crossref.api import CrossrefClient


def _client() -> CrossrefClient:
    from pipeline.ingestion.api_params import API_BASE_URLS
    from pipeline.ingestion.crossref.api import CrossrefClient

    return CrossrefClient(API_BASE_URLS["crossref"])


def _person_harvester(conn: Connection, logger: logging.Logger) -> Harvester:
    from pipeline.ingestion.crossref.person_search import CrossrefPersonHarvester

    return CrossrefPersonHarvester(conn, logger, _client())


def _doi_search() -> DoiSearch:
    from pipeline.ingestion.common.doi_search import DoiSearch
    from pipeline.ingestion.common.lookup import by_native_id

    # Un DOI alias renvoie le document de son DOI principal : le DOI cherché rejoint les absents.
    return DoiSearch(by_native_id(Source.CROSSREF, _fetch_by_native_id))


async def _fetch_by_native_id(client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
    from pipeline.ingestion.crossref.api import fetch_work

    return await fetch_work(client, source_id)


def _normalizer() -> type[SourceNormalizer]:
    from pipeline.ingestion.crossref.normalize import CrossrefNormalizer

    return CrossrefNormalizer


def _identify(record: Mapping[str, JsonValue]) -> RecordIdentity | None:
    """Renvoie l'identifiant natif d'une œuvre Crossref : son DOI."""
    from domain.documents.identifiers import DOI
    from domain.types import as_str

    doi = DOI.normalize(as_str(record.get("DOI")))
    return RecordIdentity.of(doi, doi) if doi else None


ADAPTER = SourceAdapter(
    source=Source.CROSSREF,
    identify=_identify,
    fetch_by_native_id=_fetch_by_native_id,
    normalizer=_normalizer,
    person_harvester=_person_harvester,
    doi_search=_doi_search,
)
