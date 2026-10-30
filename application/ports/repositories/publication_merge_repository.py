"""Port PublicationMergeRepository : données d'une fusion manuelle de publications."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from domain.publications.manual_merge import Attribution


class PublicationMergeRepository(Protocol):
    """Publications à fusionner, verdict de fusion et personnes de leurs contributions."""

    def dois(self, publication_ids: Sequence[int]) -> dict[int, str | None]:
        """Renvoie le DOI de chaque publication donnée existante."""
        ...

    def source_record_ids(self, publication_ids: Sequence[int]) -> list[int]:
        """Renvoie les enregistrements sources rattachés aux publications données."""
        ...

    def publications_of(self, source_record_ids: Sequence[int]) -> set[int]:
        """Renvoie les publications des enregistrements sources donnés."""
        ...

    def record_manual_merge(self, source_record_ids: Sequence[int]) -> int:
        """Enregistre la fusion manuelle des enregistrements sources donnés, par leur clé naturelle. Renvoie l'identifiant de la fusion."""
        ...

    def attributions(self, publication_ids: Sequence[int]) -> dict[int, Attribution]:
        """Renvoie, pour chaque contribution source des publications données, la personne et le mode de sa contribution, si cette contribution a une personne."""
        ...

    def contributions(self, publication_id: int) -> dict[int, set[int]]:
        """Renvoie les contributions sources de chaque contribution de la publication."""
        ...

    def write_attributions(
        self, publication_id: int, attributions: Mapping[int, Attribution]
    ) -> None:
        """Pose la personne et le mode de chaque contribution de la publication présente dans les attributions. Les autres contributions de la publication restent sans personne."""
        ...
