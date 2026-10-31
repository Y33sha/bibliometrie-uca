"""Enregistrement source : un document tel qu'une source le décrit, avant son agrégation en publication. `(source, source_id)` l'identifie : un réimport met à jour le même enregistrement source."""

from dataclasses import dataclass

from domain.publications.dates import PublicationDate
from domain.source_records.keys import DoiKeys
from domain.types import JsonValue


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """Enregistrement source, en lecture seule."""

    id: int | None
    source: str
    source_id: str
    title: str
    publication_year: int | None
    doc_type: str | None
    dois: DoiKeys
    """DOI actifs de rôle autre que `related`, cible appliquée."""
    serial_id: int | None
    monograph_id: int | None
    container_title: str | None
    language: str | None
    is_retracted: bool | None
    abstract: str | None
    countries: tuple[str, ...]
    keywords: tuple[str, ...]
    urls: tuple[str, ...]
    topics: dict[str, JsonValue] | None
    biblio: dict[str, JsonValue] | None
    source_extras: dict[str, JsonValue] | None
    license: str | None = None
    """Licence normalisée (valeur de `License`)."""
    publisher_id: int | None = None
    publication_date: PublicationDate | None = None
