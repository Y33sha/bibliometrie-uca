"""Lecture des personnes (router persons).

Le package est organisé par thème, une classe par module :
- `list` : liste, recherche, personne en administration, formes de nom
- `facets` : facettes de la liste
- `detail` : profil, thèses, adresses, tableau de bord, sujets
- `admin` : contributions par forme de nom, files de triage des formes et des identifiants
- `identifiers` : identifiants d'une personne, partagés par la liste et le profil

`PersonsQueries` réunit ces classes.
"""

from sqlalchemy import Connection

from infrastructure.read_models.persons.admin import PersonAdminQueries
from infrastructure.read_models.persons.detail import PersonDetailQueries
from infrastructure.read_models.persons.facets import PersonFacetQueries
from infrastructure.read_models.persons.list import PersonListQueries


class PersonsQueries(
    PersonListQueries, PersonFacetQueries, PersonDetailQueries, PersonAdminQueries
):
    """Lectures sur les personnes."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn


__all__ = ["PersonsQueries"]
