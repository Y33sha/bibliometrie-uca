"""Type d'une structure de recherche / d'enseignement.

`StructureType` mappe l'enum PostgreSQL `structure_type` et porte `is_affiliation` : un `SITE` sert de contexte de lieu au matching, les autres types portent un rattachement institutionnel. Les identifiants externes (`RorId`, `HalCollection`) et les formes de nom des structures vivent dans les modules voisins de `domain/structures/` ; l'édition passe par le port `structure_repository`.
"""

from enum import StrEnum


class StructureType(StrEnum):
    """Type d'une structure de recherche / d'enseignement.

    Mappe sur l'enum Postgres `structure_type`. `StrEnum` garde la valeur sérialisable telle quelle vers SQL et API.
    """

    UNIVERSITE = "universite"
    CHU = "chu"
    ECOLE = "ecole"
    LABO = "labo"
    EQUIPE = "equipe"
    SITE = "site"
    ONR = "onr"
    # Structure administrative : service (direction des systèmes d'information, bibliothèque
    # universitaire) ou structure fédérative intermédiaire (institut, sous tutelle de l'université
    # et tutelle de laboratoires).
    ADMIN = "admin"
    AUTRE = "autre"

    @property
    def is_affiliation(self) -> bool:
        """Vrai si un rattachement à une structure de ce type constitue une affiliation.

        Un site porte les formes de nom d'un lieu — communes, campus, codes postaux — pour servir de contexte de reconnaissance à d'autres structures, via `structure_name_forms.requires_context_of`. Une adresse qui le mentionne atteste d'un lieu, non d'un rattachement institutionnel : le site est un instrument du matching, jamais son résultat.
        """
        return self is not StructureType.SITE
