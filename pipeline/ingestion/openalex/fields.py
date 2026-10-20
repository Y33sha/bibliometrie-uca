"""Identifiants d'un work OpenAlex : identifiant OpenAlex et DOI."""

from __future__ import annotations

from collections.abc import Mapping

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_str
from pipeline.ingestion.openalex.payload import short_openalex_id


def extract_openalex_id(work: Mapping[str, JsonValue]) -> str:
    """ID OpenAlex court d'un work (`W2741809807`), pour servir de `source_id` en staging."""
    return short_openalex_id(as_str(work["id"]) or "")


def extract_doi(work: Mapping[str, JsonValue]) -> str | None:
    """Extrait le DOI nettoyé d'un work OpenAlex (sans préfixe URL)."""
    return clean_doi(as_str(work.get("doi")))
