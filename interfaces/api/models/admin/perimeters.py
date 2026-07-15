"""Modèles Pydantic (bodies HTTP) pour les périmètres.

Le contrat d'édition `PerimeterUpdate` vit dans le port `application/ports/repositories/perimeter_repository.py` ; les DTOs de retour des query services (`PerimeterOut`, `PerimeterStructureItem`) dans `application/ports/api/perimeters_queries.py` (cf. chantier `CODE_typage-projections-strict` Phase 4).
"""

from typing import Annotated

from pydantic import BaseModel, StringConstraints

_Trimmed = Annotated[str, StringConstraints(strip_whitespace=True)]


class AddPerimeterStructure(BaseModel):
    structure_id: int


class PerimeterCreate(BaseModel):
    code: _Trimmed
    name: _Trimmed
