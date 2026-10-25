"""Adaptateurs des sources, par source : les phases y trouvent les implémentations qu'elles câblent."""

from domain.sources.registry import Source
from pipeline.ingestion import crossref, datacite, hal, openalex, scanr, theses, wos
from pipeline.ingestion.common.adapter import SourceAdapter

ADAPTERS: dict[Source, SourceAdapter] = {
    adapter.source: adapter
    for adapter in (
        hal.ADAPTER,
        openalex.ADAPTER,
        wos.ADAPTER,
        scanr.ADAPTER,
        theses.ADAPTER,
        crossref.ADAPTER,
        datacite.ADAPTER,
    )
}
