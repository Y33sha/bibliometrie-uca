"""Entité `Perimeter` — un périmètre d'établissement, l'ensemble de structures considérées « in perimeter » pour la bibliométrie.

Identité = `id` (clé surrogate). Identifiant naturel : `code` (unique). `structure_ids` référence les aggregates Structure par leur id, sans charger les entités complètes (potentiellement plusieurs centaines par périmètre).
"""

from dataclasses import dataclass, field


@dataclass(slots=True)
class Perimeter:
    """Périmètre d'établissement."""

    id: int | None
    code: str
    name: str
    structure_ids: tuple[int, ...] = field(default=())
