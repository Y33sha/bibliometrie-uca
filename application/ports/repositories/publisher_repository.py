"""Port PublisherRepository : édition et fusion des éditeurs."""

from typing import Protocol

from pydantic import field_validator

from application.ports.model import Model
from domain.publishers.publisher import PublisherType


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
    """Contrat d'édition et de fusion des éditeurs."""

    def exists(self, publisher_id: int) -> bool:
        """Vrai si l'éditeur existe."""
        ...

    def update(self, publisher_id: int, fields: PublisherUpdate) -> bool:
        """Écrit les champs fournis de `fields` ; le nom normalisé suit le nom. Renvoie faux si l'éditeur n'existe pas."""
        ...

    # ── Fusion ─────────────────────────────────────────────────────

    def crossref_member_ids(self, publisher_id: int) -> tuple[int, ...]:
        """Renvoie les membres Crossref de l'éditeur, tirés de ses préfixes DOI."""
        ...

    def merge_publisher_into(self, target_id: int, source_id: int) -> None:
        """Fusionne l'éditeur `source_id` dans `target_id` : applique la règle de fusion de chaque donnée de l'éditeur, puis supprime la source. Les revues homonymes des deux éditeurs sont fusionnées avant."""
        ...
