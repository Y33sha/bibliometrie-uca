"""Lecture d'une ressource JSON:API de DataCite : son DOI."""

from collections.abc import Mapping

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_mapping, as_str


def record_doi(record: Mapping[str, JsonValue]) -> str | None:
    """Renvoie le DOI normalisé d'une ressource JSON:API : `attributes.doi`, à défaut `id`. `None` sans valeur exploitable."""
    attributes = record.get("attributes")
    doi_raw = as_str(as_mapping(attributes).get("doi")) or as_str(record.get("id")) or ""
    return clean_doi(doi_raw)
