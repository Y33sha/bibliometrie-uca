"""Port : résolution des affiliations sur `source_authorships`.

Implémenté par `infrastructure.pipeline.affiliations.in_perimeter.PgAffiliationsQueries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class InPerimeterSyncCounts(NamedTuple):
    """Nombre de `source_authorships` dont `in_perimeter` a changé lors d'un alignement."""

    added: int  # passées à TRUE (entrées dans le périmètre)
    removed: int  # passées à FALSE (sorties du périmètre)


class AffiliationsQueries(Protocol):
    """Pose `in_perimeter` sur les `source_authorships` depuis leurs adresses résolues (alignement de phase via la matview, ou recompute admin ciblé par ids), rafraîchit la matview qui l'alimente, et propage `in_perimeter` vers les `authorships` consolidées."""

    def sync_in_perimeter(
        self, conn: Connection, *, perimeter_ids: list[int]
    ) -> InPerimeterSyncCounts:
        """Aligne `in_perimeter` sur les structures `perimeter_ids`, lues depuis la matview, en n'écrivant que les changements."""
        ...

    def refresh_source_authorship_structures(self, conn: Connection) -> None:
        """Rafraîchit la matview `source_authorship_structures`, qui alimente `sync_in_perimeter`.

        À appeler après la matérialisation de `perimeter_structures` et la résolution des adresses, et avant le refresh de `authorship_structures`, qui en dérive.
        """
        ...

    def recompute_in_perimeter_on_source_authorships(
        self,
        conn: Connection,
        source_authorship_ids: list[int],
        perimeter_structure_ids: list[int],
    ) -> None:
        """Recalcule `source_authorships.in_perimeter` pour les signatures données, directement depuis leurs adresses résolues (`address_structures`, lien `is_confirmed IS DISTINCT FROM FALSE`) filtrées par `perimeter_structure_ids`. Variante ciblée par ids, en temps réel après une édition admin d'adresse — sans passer par la matview."""
        ...

    def propagate_in_perimeter_to_authorships(
        self, conn: Connection, source_authorship_ids: list[int]
    ) -> None:
        """Propage `in_perimeter` des signatures données vers les lignes consolidées `authorships` des paires (publication, personne) impactées."""
        ...
