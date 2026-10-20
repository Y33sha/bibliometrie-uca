"""Lecture d'un nœud JSON:API de DataCite : son DOI."""

from collections.abc import Mapping

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_mapping, as_str


def record_doi(record: Mapping[str, JsonValue]) -> str | None:
    """DOI normalisé d'un nœud JSON:API `data` : `attributes.doi`, sinon `id` (les deux portent le DOI). Passé par `clean_doi` (normalisation partagée). `None` si aucun des deux n'est présent ou exploitable."""
    attributes = record.get("attributes")
    doi_raw = as_str(as_mapping(attributes).get("doi")) or as_str(record.get("id")) or ""
    return clean_doi(doi_raw)
