"""Port : recalcul ciblé de `in_perimeter` sur des signatures, après une édition d'adresse par l'administration.

Implémenté par `pipeline.transformation.structures.in_perimeter.InPerimeterRecompute`.
"""

from typing import Protocol

from sqlalchemy import Connection


class AffiliationsQueries(Protocol):
    """Recalcul ciblé de `in_perimeter` après une édition d'adresse : sur les `source_authorships`, puis sur les `authorships` consolidées."""

    def recompute_in_perimeter_on_source_authorships(
        self,
        conn: Connection,
        source_authorship_ids: list[int],
        perimeter_structure_ids: list[int],
    ) -> None:
        """Recalcule `source_authorships.in_perimeter` pour les signatures données, directement depuis leurs adresses résolues (`address_structures`, lien `is_confirmed IS DISTINCT FROM FALSE`) filtrées par `perimeter_structure_ids`. Variante ciblée par ids, en temps réel après une édition admin d'adresse — sans passer par la matview. Un enregistrement sans publication dont une signature est dans le périmètre est marqué `keys_dirty`."""
        ...

    def propagate_in_perimeter_to_authorships(
        self, conn: Connection, source_authorship_ids: list[int]
    ) -> None:
        """Propage `in_perimeter` des signatures données vers les lignes consolidées `authorships` des paires (publication, personne) impactées."""
        ...
