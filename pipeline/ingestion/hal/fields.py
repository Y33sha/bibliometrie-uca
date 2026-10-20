"""Identité d'une notice HAL : identifiant et DOI."""

from collections.abc import Mapping

from domain.publications.identifiers import clean_doi
from domain.sources.hal import hal_text_field
from domain.types import JsonValue


def extract_id(doc: Mapping[str, JsonValue]) -> str:
    """Identifiant HAL d'une notice (champ `halId_s`), chaîne vide s'il manque."""
    return hal_text_field(doc.get("halId_s")) or ""


def extract_doi(doc: Mapping[str, JsonValue]) -> str | None:
    """DOI nettoyé d'une notice HAL (champ `doiId_s`).

    `doiId_s` arrive en scalaire depuis le moissonnage, en liste depuis la recherche par identifiant HAL : les deux formes sont gérées avant nettoyage.
    """
    return clean_doi(hal_text_field(doc.get("doiId_s")))
