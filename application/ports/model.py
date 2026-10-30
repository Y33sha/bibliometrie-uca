"""Classe de base des modèles Pydantic échangés avec l'API."""

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """Modèle Pydantic dont les docstrings de champ entrent dans le schéma JSON, donc dans l'OpenAPI."""

    model_config = ConfigDict(use_attribute_docstrings=True)
