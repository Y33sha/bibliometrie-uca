"""Entité `Perimeter` — un périmètre d'établissement, l'ensemble de structures considérées « in perimeter » pour la bibliométrie.

Identité = `id` (clé surrogate). Identifiant naturel : `code` (unique). `root_structure_ids` référence les structures racines par leur id, sans charger les entités complètes (potentiellement plusieurs centaines par périmètre).
"""

from dataclasses import dataclass, field

from domain.errors import ValidationError


def _require_nonempty(value: str | None, field_label: str) -> str:
    """Retourne `value` si non vide (espaces exclus), sinon lève `ValidationError`."""
    if value is None or not value.strip():
        raise ValidationError(f"Le {field_label} du périmètre est requis")
    return value


@dataclass(slots=True)
class Perimeter:
    """Périmètre d'établissement.

    `create` fabrique un périmètre neuf en validant code et nom ; `set_name` et `set_root_structure_ids` mutent en garantissant l'invariant (nom non vide). Le `code` est l'identifiant naturel, posé à la création et immuable ensuite.
    """

    id: int | None
    code: str
    name: str
    root_structure_ids: tuple[int, ...] = field(default=())

    @classmethod
    def create(cls, *, code: str, name: str, root_structure_ids: list[int]) -> "Perimeter":
        """Fabrique un périmètre neuf (`id` non encore attribué) en validant code et nom."""
        return cls(
            id=None,
            code=_require_nonempty(code, "code"),
            name=_require_nonempty(name, "nom"),
            root_structure_ids=tuple(root_structure_ids),
        )

    def set_name(self, name: str | None) -> None:
        """Renomme le périmètre. Lève `ValidationError` si le nom est vide."""
        self.name = _require_nonempty(name, "nom")

    def set_root_structure_ids(self, root_structure_ids: list[int] | None) -> None:
        """Fixe les structures racines du périmètre (liste vide ou `None` → aucune racine)."""
        self.root_structure_ids = tuple(root_structure_ids or ())
