"""Port PerimeterRepository — contrat d'accès à l'agrégat Perimeter."""

from typing import Annotated, Protocol

from pydantic import BaseModel, StringConstraints


class PerimeterUpdate(BaseModel):
    """Champs éditables d'un périmètre, en modification sélective.

    Seuls les champs explicitement fournis sont écrits (`model_dump(exclude_unset=True)`). `root_structure_ids` liste les structures racines ; la clôture qui en descend est matérialisée à part, et son recalcul revient au caller.
    """

    name: Annotated[str, StringConstraints(strip_whitespace=True)] | None = None
    root_structure_ids: list[int] | None = None


class PerimeterRepository(Protocol):
    """Contrat d'accès à la table `perimeters`."""

    # ── Liens structure ↔ perimeter ────────────────────────────────

    def remove_structure_from_all_perimeters(self, structure_id: int) -> None:
        """Retire une structure des racines (`root_structure_ids`) de tout périmètre, après sa suppression."""
        ...

    # ── CRUD ───────────────────────────────────────────────────────

    def perimeter_code_exists(self, code: str) -> bool: ...

    def create_perimeter(
        self,
        *,
        code: str,
        name: str,
        root_structure_ids: list[int],
    ) -> int: ...

    def update_perimeter_fields(self, perimeter_id: int, fields: PerimeterUpdate) -> None:
        """Applique une modification sélective (`PerimeterUpdate`) ; le service garantit au moins un champ fourni. Lève `NotFoundError` si le périmètre est introuvable."""
        ...

    def get_perimeter_code(self, perimeter_id: int) -> str | None: ...

    def delete_perimeter(self, perimeter_id: int) -> None: ...
