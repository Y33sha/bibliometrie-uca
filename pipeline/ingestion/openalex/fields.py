"""Champs des works OpenAlex : champs demandés à l'API, identifiant et DOI d'un work."""

from __future__ import annotations

from collections.abc import Mapping

from domain.publications.identifiers import clean_doi
from domain.sources.openalex import short_openalex_id
from domain.types import JsonValue, as_str

SELECT_FIELDS = ",".join(
    [
        "id",
        "doi",
        "title",
        "display_name",
        "publication_year",
        "publication_date",
        "type",
        "language",
        "primary_location",
        "locations",
        "authorships",
        "open_access",
        "cited_by_count",
        "fwci",
        "citation_normalized_percentile",
        "biblio",
        "is_retracted",
        "topics",
        "keywords",
        "abstract_inverted_index",
    ]
)
"""Champs demandés à l'API (`select`)."""


def extract_openalex_id(work: Mapping[str, JsonValue]) -> str:
    """ID OpenAlex court d'un work (`W2741809807`), pour servir de `source_id` en staging."""
    return short_openalex_id(as_str(work["id"]) or "")


def extract_doi(work: Mapping[str, JsonValue]) -> str | None:
    """Extrait le DOI nettoyé d'un work OpenAlex (sans préfixe URL)."""
    return clean_doi(as_str(work.get("doi")))
