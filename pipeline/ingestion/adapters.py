"""Adaptateurs des sources. Seules les phases les importent.

L'adaptateur d'une source se charge à sa première demande : le code d'une source écartée du run reste non chargé, et un défaut de ce code laisse le run se dérouler.
"""

import importlib
from functools import cache

from domain.sources.registry import Source
from pipeline.ingestion.common.adapter import SourceAdapter


@cache
def adapter(source: Source) -> SourceAdapter:
    """Renvoie l'adaptateur de `source`, déclaré dans `pipeline/ingestion/<source>/adapter.py`."""
    loaded = importlib.import_module(f"pipeline.ingestion.{source.value}.adapter").ADAPTER
    assert isinstance(loaded, SourceAdapter)
    return loaded
