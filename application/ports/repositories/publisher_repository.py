"""Port PublisherRepository : édition et fusion de l'entité Publisher."""

from typing import Protocol

from pydantic import field_validator

from application.ports.model import Model
from domain.publishers.publisher import Publisher, PublisherType


class PublisherUpdate(Model):
    """Champs modifiables d'un éditeur. Seuls les champs fournis sont écrits."""

    name: str | None = None
    country: str | None = None
    publisher_type: PublisherType | None = None

    @field_validator("country")
    @classmethod
    def _country_lowercase(cls, v: str | None) -> str | None:
        # Code pays en minuscules (comme countries.code et addresses.countries).
        return v.lower() if v else v


class PublisherRepository(Protocol):
    """Contrat d'édition et de fusion de l'entité Publisher."""

    def find_by_id(self, publisher_id: int) -> Publisher | None:
        """Charge l'entité `Publisher`, ou `None` si l'éditeur n'existe pas. Ses formes de nom sont hors de l'entité."""
        ...

    def save(self, publisher: Publisher) -> None:
        """Enregistre les champs modifiables d'un éditeur chargé. Lève `NotFoundError` si l'éditeur n'existe pas."""
        ...

    # ── Fusion ─────────────────────────────────────────────────────

    def crossref_member_ids(self, publisher_id: int) -> tuple[int, ...]:
        """Renvoie les membres Crossref de l'éditeur, tirés de ses préfixes DOI."""
        ...

    def merge_publisher_into(self, target_id: int, source_id: int) -> None:
        """Fusionne l'éditeur `source_id` dans `target_id` : applique la règle de fusion de chaque donnée de l'éditeur, puis supprime la source. Les revues homonymes des deux éditeurs sont fusionnées avant."""
        ...
