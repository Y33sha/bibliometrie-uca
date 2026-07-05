"""Aggregate root ``Perimeter`` — entité métier d'un périmètre
d'établissement (ensemble de structures considérées comme « in
perimeter » pour la bibliométrie).

Identité = `id` (clé surrogate). Identifiant naturel : `code`
(unique).

`structure_ids` est conservé en `tuple[int, ...]` (référence par id à
des aggregates Structure — pattern Cosmic Python ch. 7). La hydratation
ne charge pas les entités Structure complètes (potentiellement
plusieurs centaines par perimeter).

Scaffolding a minima : pas d'invariants métier rapatriés ici, à
enrichir si nécessaire.
"""

from dataclasses import dataclass, field


@dataclass(slots=True)
class Perimeter:
    """Périmètre d'établissement (aggregate root)."""

    id: int | None
    code: str
    name: str
    structure_ids: tuple[int, ...] = field(default=())
