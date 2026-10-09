"""Port du référentiel ROR (`ror_organizations`, `ror_relations`, `ror_dump_imports`)."""

from collections.abc import Iterable, Sequence
from typing import Protocol

from domain.structures.identifiers import RorId
from domain.structures.ror import RorOrganization


class RorRepository(Protocol):
    """Contrat d'accès au référentiel ROR."""

    def replace_all(
        self,
        organizations: Sequence[RorOrganization],
        relations: Iterable[tuple[RorId, RorId]],
        *,
        version: str,
    ) -> None:
        """Vide les deux tables, y écrit les organisations et les couples `(parent, enfant)`, et inscrit `version` dans `ror_dump_imports`."""
        ...

    def last_imported_version(self) -> str | None:
        """Version du dernier import, `None` sans import."""
        ...
