"""Aggregate root `Publication` — référence biblio canonique.

Une `Publication` unifie les images qu'une ou plusieurs `SourceRecord` donnent d'un même document scientifique. Clé surrogate : `id`. Identifiant naturel principal : `doi` (quand renseigné ; les autres identifiants — HALId, NNT — sont dans `source_record_identifiers`).

Les `source_records` attachées sont lues en projection (`SourceRecord`), jamais comme un agrégat mutable.

L'entité contient les métadonnées retenues pour la publication. Les règles qui la calculent vivent dans les modules voisins du domaine : agrégation cross-sources (`aggregation`), arbitrage des statuts et canonicalisation des titres (`metadata`), assignation et réconciliation (`reconciliation`).
"""

from dataclasses import dataclass, field

from domain.publications.identifiers import DOI
from domain.types import JsonValue


@dataclass(slots=True)
class Publication:
    """Référence biblio canonique (aggregate root).

    Le champ `id` est None tant que la publication n'a pas été persistée ; il est positionné par le repository après insertion.
    """

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
