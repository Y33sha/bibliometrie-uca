"""Port PerimeterRepository : accès à l'entité Perimeter."""

from typing import Annotated, Protocol

from pydantic import BaseModel, StringConstraints

from domain.perimeters.perimeter import Perimeter


class PerimeterUpdate(BaseModel):
    """Champs modifiables d'un périmètre. Seuls les champs fournis sont écrits."""

    name: Annotated[str, StringConstraints(strip_whitespace=True)] | None = None
    root_structure_ids: list[int] | None = None
    """Structures racines. L'appelant recalcule leurs sous-structures (`perimeter_structures`)."""


class PerimeterRepository(Protocol):
    """Contrat d'accès à l'entité Perimeter."""

    # ── Entité : chargement et écriture ───────────────────────────

    def find_by_id(self, perimeter_id: int) -> Perimeter | None:
        """Charge l'entité `Perimeter`, ou `None` si le périmètre est introuvable."""
        ...

    def add(self, perimeter: Perimeter) -> int:
        """Insère un périmètre et renvoie son id."""
        ...

    def save(self, perimeter: Perimeter) -> None:
        """Enregistre les champs éditables d'un périmètre chargé. Le code est immuable.

        Raises:
            NotFoundError: périmètre introuvable.
        """
        ...

    # ── Liens aux structures ───────────────────────────────────────

    def remove_structure_from_all_perimeters(self, structure_id: int) -> None:
        """Retire une structure des racines (`root_structure_ids`) de tout périmètre, après sa suppression."""
        ...

    # ── Autres accès ───────────────────────────────────────────────

    def perimeter_code_exists(self, code: str) -> bool: ...

    def get_perimeter_code(self, perimeter_id: int) -> str | None: ...

    def delete_perimeter(self, perimeter_id: int) -> None: ...
