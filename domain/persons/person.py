"""Nom d'une personne, et motifs de son exclusion."""

from enum import StrEnum

from domain.errors import ValidationError


def validated_name(last_name: str, first_name: str) -> tuple[str, str]:
    """Renvoie le nom et le prénom sans les espaces qui les entourent.

    Raises:
        ValidationError: nom de famille vide, dont dérivent les formes de nom.
    """
    last_name, first_name = last_name.strip(), first_name.strip()
    if not last_name:
        raise ValidationError("Le nom est requis")
    return last_name, first_name


class PersonExclusion(StrEnum):
    """Motif d'exclusion d'une personne, décidé à la main. Une personne exclue est absente de l'interface publique et du périmètre. Ses formes de nom servent au matching. Une personne qui a une fiche RH est valide."""

    NOT_A_PERSON = "not_a_person"
    """Fausse entité : nom d'équipe, plusieurs noms dans un même champ…"""
    OUT_OF_PERIMETER = "out_of_perimeter"
    """Personne réelle, rattachée au périmètre par erreur."""


def check_exclusion(exclusion: PersonExclusion | None, *, has_hr_record: bool) -> None:
    """Valide le motif d'exclusion d'une personne.

    Raises:
        ValidationError: exclusion d'une personne qui a une fiche RH.
    """
    if exclusion is not None and has_hr_record:
        raise ValidationError("Une personne qui a une fiche RH est valide")
