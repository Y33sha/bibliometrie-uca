"""Adaptateur de la source, câblé par les phases."""

from domain.sources.registry import Source
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.common.adapter import SourceAdapter
from pipeline.ingestion.common.doi_search import DoiSearch
from pipeline.ingestion.common.lookup import by_native_id
from pipeline.ingestion.crossref.api import CrossrefClient, fetch_work
from pipeline.ingestion.crossref.normalize import CrossrefNormalizer
from pipeline.ingestion.crossref.person_search import CrossrefPersonHarvester


def _client() -> CrossrefClient:
    return CrossrefClient(API_BASE_URLS["crossref"])


ADAPTER = SourceAdapter(
    source=Source.CROSSREF,
    fetch_by_native_id=fetch_work,
    normalizer=CrossrefNormalizer,
    person_harvester=lambda conn, logger: CrossrefPersonHarvester(conn, logger, _client()),
    # Un DOI alias renvoie le document de son DOI principal : le DOI cherché rejoint les absents.
    doi_search=DoiSearch(by_native_id(Source.CROSSREF, fetch_work)),
)
