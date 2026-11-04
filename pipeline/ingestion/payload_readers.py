"""Lecteurs des documents reçus des sources.

Le lecteur d'une source se charge à sa première demande : le code d'une source écartée du run reste non chargé.
"""

import importlib
from functools import cache

from domain.sources.registry import Source
from pipeline.ingestion.common.adapter import PayloadReader


@cache
def payload_reader(source: Source) -> PayloadReader:
    """Renvoie le lecteur des documents de `source`, déclaré dans son paquet (`pipeline/ingestion/<source>/__init__.py`)."""
    reader = importlib.import_module(f"pipeline.ingestion.{source.value}").READER
    assert isinstance(reader, PayloadReader)
    return reader
