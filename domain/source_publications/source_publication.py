"""Entité `SourcePublication` — l'image d'un document dans une source externe.

Une `SourcePublication` représente un document tel que remonté par une source (HAL, OpenAlex, WoS, theses.fr, ScanR, …), avant agrégation dans la `Publication` canonique. Identité : `id` (surrogate) / `(source, source_id)` (naturelle) ; un réimport met à jour la même entité.

Immuable (frozen), utilisée en lecture seule : jamais persistée via cet objet — les écritures passent par le SQL. Consommée par `refresh_from_sources` / `_refresh_aggregate` (agrégation canonique des métadonnées). La correction de métadonnées, elle, opère sur son propre contrat d'entrée (`MetadataForCorrection`, cf. `correction.py`), pas sur cette entité.
"""

from dataclasses import dataclass

from domain.types import JsonValue


@dataclass(frozen=True, slots=True)
class SourcePublication:
    """Document tel qu'extrait d'une source externe, chargé pour lecture."""

    id: int | None
    source: str
    source_id: str
    title: str
    pub_year: int | None
    doc_type: str | None
    doi: str | None
    journal_id: int | None
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
    meta: dict[str, JsonValue] | None
