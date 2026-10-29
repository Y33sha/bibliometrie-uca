"""Publication : l'entité unifiée que le pipeline dérive des enregistrements sources d'un même document."""

from dataclasses import dataclass, field

from domain.publications.identifiers import DOI
from domain.types import JsonValue


@dataclass(slots=True)
class Publication:
    """Publication ; `id` vaut `None` avant son insertion en base."""

    id: int | None
    title: str
    publication_year: int
    title_normalized: str | None = None
    doc_type: str | None = None
    doi: DOI | None = None
    oa_status: str | None = None
    # Licence de la version éditeur, et licence du fichier déposé dans HAL (valeurs de `License`).
    license: str | None = None
    deposit_license: str | None = None
    # Adresse de la meilleure copie ouverte (`domain.publications.access`).
    best_copy_url: str | None = None
    serial_id: int | None = None
    monograph_id: int | None = None
    # Éditeur à la date de publication (`domain.publishers.attribution`).
    publisher_id: int | None = None
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
