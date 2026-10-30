"""Champs des documents ScanR : identifiant et DOI."""

from __future__ import annotations

from collections.abc import Mapping

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_mapping, as_sequence, as_str


def extract_id(doc: Mapping[str, JsonValue]) -> str:
    """Renvoie l'identifiant ScanR d'un document (champ `id`)."""
    return as_str(doc.get("id")) or ""


def extract_dois(doc: Mapping[str, JsonValue]) -> list[str]:
    """Renvoie les DOI nettoyés des `externalIds` d'un document ScanR, dans leur ordre."""
    return [
        doi
        for entry in as_sequence(doc.get("externalIds"))
        if as_str((ext := as_mapping(entry)).get("type")) == "doi"
        and (doi := clean_doi(as_str(ext.get("id"))))
    ]


def extract_doi(doc: Mapping[str, JsonValue]) -> str | None:
    """Renvoie le premier DOI nettoyé des `externalIds` d'un document ScanR."""
    dois = extract_dois(doc)
    return dois[0] if dois else None
