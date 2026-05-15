"""Aggregate root ``Publisher`` — entité métier d'un éditeur.

Identité = `id` (clé surrogate). Identifiant naturel : `name`
(via la normalisation côté `publisher_name_forms`).

La logique métier touchant aux éditeurs (matching, fusion, détection
predatory) vit ici. Scaffolding a minima : pas d'invariants métier
identifiés aujourd'hui, à enrichir si nécessaire.
"""

from dataclasses import dataclass


@dataclass(slots=True)
class Publisher:
    """Éditeur (aggregate root)."""

    id: int | None
    name: str
    country: str | None = None
    openalex_id: str | None = None
    is_predatory: bool = False
    notes: str | None = None
    doi_prefix: str | None = None
