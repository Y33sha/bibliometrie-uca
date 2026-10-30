"""Modèles de réponse : lecture du référentiel des pays.

Le référentiel alimente les listes de choix d'attribution et de filtre par pays.
"""

from application.ports.model import Model


class CountryOut(Model):
    """Pays du référentiel : code ISO à deux lettres et libellé."""

    code: str
    name: str
