"""Entité ``SourceAuthorship`` — entité fille de l'aggregate
``SourcePublication``.

Représente une signature d'auteur telle que remontée par une source
externe (HAL, OpenAlex, WoS, theses.fr, ScanR). FK obligatoire vers le
root via `source_publication_id NOT NULL` (sens DDD strict — lifecycle
lié au root, accès via le root).

`authorship_id` (nullable) pointe vers l'`Authorship` canonique
agrégeant cette signature après dédup. `person_id` (nullable) est
résolu par la cascade de matching.

La logique métier touchant aux authorships sources (matching personne,
résolution de structures, scope de périmètre côté source) vit ici.
"""

from dataclasses import dataclass

from domain.types import JsonValue


@dataclass(slots=True)
class SourceAuthorship:
    """Signature d'auteur dans une publication source.

    Identité : `id` (clé surrogate). FK obligatoire vers le root via
    `source_publication_id`. Le `source` (text, ex. "hal", "wos") est
    redondant avec celui de la `SourcePublication` parente mais conservé
    pour les requêtes inverses.
    """

    id: int | None
    source_publication_id: int
    source: str
    author_position: int | None = None
    person_id: int | None = None
    authorship_id: int | None = None
    raw_author_name: str | None = None
    author_name_normalized: str | None = None
    in_perimeter: bool = False
    is_corresponding: bool = False
    roles: tuple[str, ...] = ("author",)
    structure_ids: tuple[int, ...] = ()
    source_structures: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    person_identifiers: dict[str, JsonValue] | None = None
    source_data: dict[str, JsonValue] | None = None
