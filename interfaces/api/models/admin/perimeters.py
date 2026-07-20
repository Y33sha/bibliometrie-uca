"""Modèles Pydantic du router des périmètres : corps des requêtes entrantes.

Le contrat d'édition `PerimeterUpdate` vit dans le port `application/ports/repositories/perimeter_repository.py`.
"""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

_Trimmed = Annotated[str, StringConstraints(strip_whitespace=True)]

# Un code de périmètre sert d'identifiant naturel : la configuration du pipeline le désigne par
# sa valeur (`perimeter_persons`, `perimeter_extraction`). Il se restreint donc aux minuscules,
# chiffres, tiret et souligné, pour rester citable tel quel.
_PerimeterCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50, pattern=r"^[a-z0-9_-]+$"),
]


class PerimeterCreate(BaseModel):
    code: _PerimeterCode
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    structure_ids: list[int] = Field(default_factory=list)
