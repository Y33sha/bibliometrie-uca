"""Modèles Pydantic du router des périmètres : corps des requêtes entrantes.

Le contrat d'édition `PerimeterUpdate` vit dans le port `application/ports/repositories/perimeter_repository.py`.
"""

from typing import Annotated

from pydantic import BaseModel, StringConstraints

_Trimmed = Annotated[str, StringConstraints(strip_whitespace=True)]


class AddPerimeterStructure(BaseModel):
    structure_id: int


class PerimeterCreate(BaseModel):
    code: _Trimmed
    name: _Trimmed
