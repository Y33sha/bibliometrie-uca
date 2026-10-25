"""Entité `SourceRecord` — l'image d'un document dans une source externe.

Un `SourceRecord` représente un document tel que remonté par une source (HAL, OpenAlex, WoS, theses.fr, ScanR, …), avant agrégation dans la `Publication` du référentiel. Clés : `id` (surrogate), `(source, source_id)` (naturelle) ; un réimport met à jour la même entité.

Immuable (frozen), utilisée en lecture seule : jamais persistée via cet objet — les écritures passent par le SQL. Consommée par `refresh_from_sources`, l'agrégation des métadonnées. La correction des métadonnées lit son propre contrat d'entrée, `MetadataForCorrection`.
"""

from dataclasses import dataclass

from domain.types import JsonValue


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """Document tel qu'extrait d'une source externe, chargé pour lecture."""

    id: int | None
    source: str
    source_id: str
    title: str
    publication_year: int | None
    doc_type: str | None
    doi: str | None
    serial_id: int | None
    monograph_id: int | None
    container_title: str | None
    language: str | None
    oa_status: str | None
    is_retracted: bool | None
    abstract: str | None
    countries: tuple[str, ...]
    keywords: tuple[str, ...]
    urls: tuple[str, ...]
    topics: dict[str, JsonValue] | None
    biblio: dict[str, JsonValue] | None
    source_extras: dict[str, JsonValue] | None
    # Licence normalisée (valeur de `License`).
    license: str | None = None
    publisher_id: int | None = None
