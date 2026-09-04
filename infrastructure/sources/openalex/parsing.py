"""Parsing pur des works OpenAlex (sans I/O).

Partagé par l'adapter d'extraction (`extract_openalex`) et l'adapter fetch-missing-doi (`fetch_missing_doi`) : ne dépend que du format JSON OpenAlex, ni de la connexion ni de l'auth.
"""

from __future__ import annotations

from collections.abc import Mapping

from domain.publications.identifiers import clean_doi
from domain.sources.openalex import short_openalex_id
from domain.types import JsonValue, as_str


def extract_openalex_id(work: Mapping[str, JsonValue]) -> str:
    """ID OpenAlex court d'un work (`W2741809807`), pour servir de `source_id` en staging."""
    return short_openalex_id(as_str(work["id"]) or "")


def extract_doi(work: Mapping[str, JsonValue]) -> str | None:
    """Extrait le DOI nettoyé d'un work OpenAlex (sans préfixe URL)."""
    return clean_doi(as_str(work.get("doi")))
