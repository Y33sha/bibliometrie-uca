"""Types des structures de recherche et d'enseignement : laboratoire, école doctorale, université, hôpital…"""

from enum import StrEnum


class StructureType(StrEnum):
    """Type de structure. Reflet du type PostgreSQL `structure_type`."""

    UNIVERSITE = "universite"
    CHU = "chu"
    ECOLE = "ecole"
    LABO = "labo"
    EQUIPE = "equipe"
    SITE = "site"
    ONR = "onr"
    ADMIN = "admin"
    """Service (direction des systèmes d'information, bibliothèque universitaire) ou structure fédérative (institut, sous tutelle de l'université et tutelle de laboratoires)."""
    AUTRE = "autre"

    @property
    def is_affiliation(self) -> bool:
        """Vrai si un rattachement à une structure de ce type est une affiliation. Les formes de nom d'un site sont celles d'un lieu (commune, campus, code postal), qui sert de contexte à la reconnaissance d'autres structures (`requires_context_of`)."""
        return self is not StructureType.SITE
