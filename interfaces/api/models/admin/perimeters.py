"""Modèles Pydantic du router des périmètres : corps des requêtes entrantes.

Le contrat d'édition `PerimeterUpdate` vit dans le port `application/ports/repositories/perimeter_repository.py`.
"""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

_Trimmed = Annotated[str, StringConstraints(strip_whitespace=True)]

# Un code de périmètre sert d'identifiant naturel : la configuration du pipeline le désigne par
# sa valeur (`perimeter_persons`, `perimeter_extraction`), comparée par égalité. Il est donc un
# jeton unique, sans espace où une incohérence de saisie ferait échouer l'appariement en silence.
_PerimeterCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50, pattern=r"^\S+$"),
]


class PerimeterCreate(BaseModel):
    code: _PerimeterCode
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    structure_ids: list[int] = Field(default_factory=list)
