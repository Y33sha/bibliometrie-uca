"""Modèles de réponse : lecture du référentiel des pays.

Le référentiel alimente les listes de choix d'attribution et de filtre par pays.
"""

from pydantic import BaseModel


class CountryOut(BaseModel):
    """Pays du référentiel : code ISO à deux lettres et libellé."""

    code: str
    name: str
