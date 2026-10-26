"""Modèles de réponse : lecture du référentiel des pays.

Le référentiel sert les listes de choix partout où un pays s'attribue ou se filtre.
"""

from pydantic import BaseModel


class CountryOut(BaseModel):
    """Pays du référentiel : code ISO à deux lettres et libellé."""

    code: str
    name: str
