"""Homonyme d'une personne rejetée : fiche exclue hors périmètre, au nom de la personne, qui réunit les contributions des publications rejetées pour elle. Son profil départage ensuite la personne et l'homonyme (`domain.persons.tie_break`)."""

from collections.abc import Mapping, Sequence

from domain.persons.name_matching import names_compatible

type Name = tuple[str, str]
"""Nom de famille et prénom normalisés."""


def homonym_contribution(person: Name, contributions: Mapping[int, Sequence[Name]]) -> int | None:
    """Renvoie la contribution d'une publication rejetée pour une personne qui rejoint l'homonyme de la personne : la seule dont une contribution source a un nom compatible avec celui de la personne (`names_compatible`). Renvoie `None` pour aucune ou plusieurs.

    Args:
        contributions: noms des contributions sources de chaque contribution sans personne de la publication.
    """
    matching = [
        contribution_id
        for contribution_id, names in contributions.items()
        if any(names_compatible(*name, *person) for name in names)
    ]
    return matching[0] if len(matching) == 1 else None
