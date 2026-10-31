"""Publication : l'entité unifiée dérivée par le pipeline des enregistrements sources d'un même document."""

from dataclasses import dataclass, field

from domain.publications.dates import PublicationDate
from domain.publications.identifiers import DOI
from domain.types import JsonValue


@dataclass(slots=True)
class Publication:
    """Publication."""

    id: int | None
    """`None` avant l'insertion en base."""
    title: str
    publication_year: int
    publication_date: PublicationDate | None = None
    """Date de publication, avec sa précision ; `publication_year` est son année."""
    title_normalized: str | None = None
    doc_type: str | None = None
    doi: DOI | None = None
    oa_status: str | None = None
    license: str | None = None
    """Licence de la version éditeur (valeur de `License`)."""
    deposit_license: str | None = None
    """Licence du fichier déposé dans HAL (valeur de `License`)."""
    best_copy_url: str | None = None
    """Adresse de la meilleure copie ouverte (`domain.publications.access`)."""
    serial_id: int | None = None
    monograph_id: int | None = None
    publisher_id: int | None = None
    """Éditeur à la date de publication (`domain.publishers.attribution`)."""
    container_title: str | None = None
    language: str | None = None
    abstract: str | None = None
    is_retracted: bool = False
    countries: tuple[str, ...] = field(default=())
    keywords: tuple[str, ...] = field(default=())
    topics: dict[str, JsonValue] | None = None
    biblio: dict[str, JsonValue] | None = None
    source_extras: dict[str, JsonValue] | None = None
    corrections: dict[str, JsonValue] = field(default_factory=dict)
    """Valeur d'avant correction et règle de chaque champ corrigé (`domain.source_records.corrections`)."""
