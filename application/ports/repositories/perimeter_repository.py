"""Port PerimeterRepository — contrat d'accès à l'agrégat Perimeter."""

from typing import Annotated, Protocol

from pydantic import BaseModel, StringConstraints

from domain.perimeters.perimeter import Perimeter


class PerimeterUpdate(BaseModel):
    """Champs éditables d'un périmètre, en modification sélective.

    Seuls les champs explicitement fournis sont écrits (`model_dump(exclude_unset=True)`). `root_structure_ids` liste les structures racines ; la clôture qui en descend est matérialisée à part, et son recalcul revient au caller.
    """

    name: Annotated[str, StringConstraints(strip_whitespace=True)] | None = None
    root_structure_ids: list[int] | None = None


class PerimeterRepository(Protocol):
    """Contrat d'accès à la table `perimeters`."""

    # ── perimeters : charger-muter-sauver l'agrégat ────────────────

    def find_by_id(self, perimeter_id: int) -> Perimeter | None:
        """Hydrate l'aggregate `Perimeter` complet (code, name, `root_structure_ids`). Retourne None si le perimeter n'existe pas. `root_structure_ids` reste sous forme d'ids (références par id à l'aggregate Structure)."""
        ...

    def add(self, perimeter: Perimeter) -> int:
        """Insère un périmètre neuf et retourne son id."""
        ...

    def save(self, perimeter: Perimeter) -> None:
        """Persiste un périmètre chargé : UPDATE de ses champs éditables (`code` immuable exclu). Lève `NotFoundError` si l'id est absent."""
        ...

    # ── Liens structure ↔ perimeter ────────────────────────────────

    def remove_structure_from_all_perimeters(self, structure_id: int) -> None:
        """Retire une structure des racines (`root_structure_ids`) de tout périmètre, après sa suppression."""
        ...

    # ── Autres accès ───────────────────────────────────────────────

    def perimeter_code_exists(self, code: str) -> bool: ...

    def get_perimeter_code(self, perimeter_id: int) -> str | None: ...

    def delete_perimeter(self, perimeter_id: int) -> None: ...
