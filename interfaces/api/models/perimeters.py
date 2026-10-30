"""Modèles Pydantic du router des périmètres : corps des requêtes entrantes.

Le contrat d'édition `PerimeterUpdate` est déclaré dans le port `application/ports/repositories/perimeter_repository.py`.
"""

from typing import Annotated

from pydantic import Field, StringConstraints

from application.ports.model import Model

_Trimmed = Annotated[str, StringConstraints(strip_whitespace=True)]

# Code de périmètre : jeton sans espace, comparé par égalité aux réglages du pipeline (`perimeter_persons`, `perimeter_extraction`).
_PerimeterCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50, pattern=r"^\S+$"),
]


class PerimeterCreate(Model):
    code: _PerimeterCode
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    root_structure_ids: list[int] = Field(default_factory=list)
