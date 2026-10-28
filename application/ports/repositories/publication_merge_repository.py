"""Port PublicationMergeRepository — données d'une fusion manuelle de publications."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from domain.publications.manual_merge import Attribution


class PublicationMergeRepository(Protocol):
    """Publications à fusionner, verdict de fusion et personnes de leurs contributions."""

    def dois(self, publication_ids: Sequence[int]) -> dict[int, str | None]:
        """DOI de chacune des publications `publication_ids` qui existe."""
        ...

    def source_record_ids(self, publication_ids: Sequence[int]) -> list[int]:
        """Enregistrements sources rattachés aux publications `publication_ids`."""
        ...

    def publications_of(self, source_record_ids: Sequence[int]) -> set[int]:
        """Publications auxquelles les enregistrements sources `source_record_ids` sont rattachés."""
        ...

    def record_manual_merge(self, source_record_ids: Sequence[int]) -> int:
        """Enregistre la fusion manuelle des enregistrements sources `source_record_ids`, par leur clé naturelle. Rend son identifiant."""
        ...

    def attributions(self, publication_ids: Sequence[int]) -> dict[int, Attribution]:
        """Personne et mode de la contribution de chaque contribution source des publications `publication_ids`, pour les contributions qui ont une personne."""
        ...

    def contributions(self, publication_id: int) -> dict[int, set[int]]:
        """Contributions sources de chaque contribution de la publication."""
        ...

    def write_attributions(
        self, publication_id: int, attributions: Mapping[int, Attribution]
    ) -> None:
        """Pose la personne et le mode de chaque contribution de la publication présente dans `attributions`. Les autres contributions de la publication restent sans personne."""
        ...
