"""Entité `Perimeter` — un périmètre d'établissement, l'ensemble de structures considérées « in perimeter » pour la bibliométrie.

Identité = `id` (clé surrogate). Identifiant naturel : `code` (unique). `root_structure_ids` référence les structures racines par leur id, sans charger les entités complètes (potentiellement plusieurs centaines par périmètre).
"""

from dataclasses import dataclass, field


@dataclass(slots=True)
class Perimeter:
    """Périmètre d'établissement."""

    id: int | None
    code: str
    name: str
    root_structure_ids: tuple[int, ...] = field(default=())
