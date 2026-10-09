"""Port du référentiel ROR (`ror_organizations`, `ror_relations`)."""

from collections.abc import Iterable, Sequence
from typing import Protocol

from domain.structures.identifiers import RorId
from domain.structures.ror import RorOrganization


class RorRepository(Protocol):
    """Contrat d'écriture du référentiel ROR."""

    def replace_all(
        self,
        organizations: Sequence[RorOrganization],
        relations: Iterable[tuple[RorId, RorId]],
    ) -> None:
        """Vide les deux tables, puis y écrit les organisations et les couples `(parent, enfant)`."""
        ...
