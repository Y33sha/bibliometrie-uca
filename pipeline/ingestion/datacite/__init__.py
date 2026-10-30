"""Source DataCite : moissonnage, paramètres de requête, empreinte des ressources JSON:API."""

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
    from pipeline.ingestion.datacite.api import DataciteClient


def _client() -> DataciteClient:
    from pipeline.ingestion.api_params import API_BASE_URLS
    from pipeline.ingestion.datacite.api import DataciteClient

    return DataciteClient(API_BASE_URLS["datacite"])


def _harvester(conn: Connection, logger: logging.Logger) -> Harvester:
    from pipeline.ingestion.datacite.harvest import DataciteHarvester

    return DataciteHarvester(conn, logger, _client())


def _person_harvester(conn: Connection, logger: logging.Logger) -> Harvester:
    from pipeline.ingestion.datacite.person_search import DatacitePersonHarvester

    return DatacitePersonHarvester(conn, logger, _client())


def _doi_search() -> DoiSearch:
    from pipeline.ingestion.datacite.fetch_missing import DataciteDoiSearch

    return DataciteDoiSearch()


def _stale_refetch() -> StaleRefetch:
    from pipeline.ingestion.datacite.fetch_stale import DataciteStaleRefetch

    return DataciteStaleRefetch()


def _normalizer() -> type[SourceNormalizer]:
    from pipeline.ingestion.datacite.normalize import DataciteNormalizer

    return DataciteNormalizer


def _strip_volatile(raw_data: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    from pipeline.ingestion.datacite.hash_normalize import strip_volatile_for_hash

    return strip_volatile_for_hash(raw_data)


def _identify(record: Mapping[str, JsonValue]) -> RecordIdentity | None:
    """Renvoie l'identifiant natif d'une ressource DataCite : son DOI."""
    from pipeline.ingestion.datacite.fields import record_doi

    doi = record_doi(record)
    return RecordIdentity.of(doi, doi) if doi else None


ADAPTER = SourceAdapter(
    source=Source.DATACITE,
    identify=_identify,
    stale_refetch=_stale_refetch,
    normalizer=_normalizer,
    harvester=_harvester,
    person_harvester=_person_harvester,
    doi_search=_doi_search,
    strip_volatile=_strip_volatile,
)
