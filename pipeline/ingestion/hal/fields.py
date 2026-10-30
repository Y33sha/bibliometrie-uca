"""Identifiants d'un document HAL : identifiant HAL et DOI."""

from collections.abc import Mapping

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue
from pipeline.ingestion.hal.payload import hal_text_field


def extract_id(doc: Mapping[str, JsonValue]) -> str:
    """Renvoie l'identifiant HAL d'un document (champ `halId_s`), ou une chaîne vide s'il manque."""
    return hal_text_field(doc.get("halId_s")) or ""


def extract_doi(doc: Mapping[str, JsonValue]) -> str | None:
    """Renvoie le DOI nettoyé d'un document HAL (champ `doiId_s`).

    `doiId_s` arrive en scalaire depuis le moissonnage, en liste depuis la recherche par identifiant HAL : les deux formes passent au nettoyage.
    """
    return clean_doi(hal_text_field(doc.get("doiId_s")))
