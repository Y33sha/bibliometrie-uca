"""Périmètre : ensemble de structures, désigné par ses structures racines."""

from dataclasses import dataclass, field

from domain.errors import ValidationError


def _require_nonempty(value: str | None, field_label: str) -> str:
    """`value`, ou `ValidationError` si elle est vide ou blanche."""
    if value is None or not value.strip():
        raise ValidationError(f"Le {field_label} du périmètre est requis")
    return value


@dataclass(slots=True)
class Perimeter:
    """Périmètre. Son `code` l'identifie et reste fixe après la création. Le code et le nom sont non vides."""

    id: int | None
    code: str
    name: str
    root_structure_ids: tuple[int, ...] = field(default=())

    @classmethod
    def create(cls, *, code: str, name: str, root_structure_ids: list[int]) -> Perimeter:
        """Périmètre à enregistrer, sans `id`."""
        return cls(
            id=None,
            code=_require_nonempty(code, "code"),
            name=_require_nonempty(name, "nom"),
            root_structure_ids=tuple(root_structure_ids),
        )

    def set_name(self, name: str | None) -> None:
        self.name = _require_nonempty(name, "nom")

    def set_root_structure_ids(self, root_structure_ids: list[int] | None) -> None:
        """`None` vaut une liste vide."""
        self.root_structure_ids = tuple(root_structure_ids or ())
