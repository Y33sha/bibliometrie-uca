"""Source Crossref : recherche par DOI et par personne, nouvelle lecture des documents."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING

from domain.sources.registry import Source
from domain.types import JsonValue
from pipeline.ingestion.common.adapter import RecordIdentity, SourceAdapter

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from pipeline.ingestion.common.doi_search import DoiSearch
    from pipeline.ingestion.common.harvester import Harvester
    from pipeline.ingestion.common.normalizer import SourceNormalizer
    from pipeline.ingestion.common.stale_refetch import StaleRefetch
    from pipeline.ingestion.crossref.api import CrossrefClient


def _client() -> CrossrefClient:
    from pipeline.ingestion.api_params import API_BASE_URLS
    from pipeline.ingestion.crossref.api import CrossrefClient

    return CrossrefClient(API_BASE_URLS["crossref"])


def _person_harvester(conn: Connection, logger: logging.Logger) -> Harvester:
    from pipeline.ingestion.crossref.person_search import CrossrefPersonHarvester

    return CrossrefPersonHarvester(conn, logger, _client())


def _doi_search() -> DoiSearch:
    from pipeline.ingestion.crossref.fetch_missing import CrossrefDoiSearch

    return CrossrefDoiSearch()


def _stale_refetch() -> StaleRefetch:
    from pipeline.ingestion.crossref.fetch_stale import CrossrefStaleRefetch

    return CrossrefStaleRefetch()


def _normalizer() -> type[SourceNormalizer]:
    from pipeline.ingestion.crossref.normalize import CrossrefNormalizer

    return CrossrefNormalizer


def _identify(record: Mapping[str, JsonValue]) -> RecordIdentity | None:
    """Renvoie l'identifiant natif d'une œuvre Crossref : son DOI."""
    from domain.publications.identifiers import clean_doi
    from domain.types import as_str

    doi = clean_doi(as_str(record.get("DOI")))
    return RecordIdentity.of(doi, doi) if doi else None


ADAPTER = SourceAdapter(
    source=Source.CROSSREF,
    identify=_identify,
    stale_refetch=_stale_refetch,
    normalizer=_normalizer,
    person_harvester=_person_harvester,
    doi_search=_doi_search,
)
