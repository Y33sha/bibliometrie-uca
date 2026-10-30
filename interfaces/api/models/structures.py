"""Modèles Pydantic du router des structures : corps des requêtes entrantes et réponses composées après mutation.

Les contrats de création et d'édition des structures et de leurs formes de nom sont déclarés dans le port `application/ports/repositories/structure_repository.py`.
"""

from pydantic import BaseModel

# ----- Corps des requêtes -----


class TutelleCreate(BaseModel):
    parent_id: int
    child_id: int


# ----- Réponses composées par le router -----


class StructureTutelleCreateResponse(BaseModel):
    """Réponse de POST /api/structures/tutelles : la tutelle créée, ou `{status: "already_exists"}`."""

    id: int | None = None
    parent_id: int | None = None
    child_id: int | None = None
    status: str | None = None
