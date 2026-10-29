"""Fusion de deux personnes : rôles des deux personnes, exclusion de la personne fusionnée."""

from collections.abc import Collection

from domain.errors import ConflictError
from domain.persons.person import PersonExclusion


def merge_roles(target_id: int, source_id: int, *, with_rh: Collection[int]) -> tuple[int, int]:
    """Personnes conservée et absorbée d'une fusion demandée de `source` dans `target`. Une personne qui a une fiche RH est conservée. `with_rh` : personnes qui ont une fiche RH. Lève `ConflictError` si les deux en ont une."""
    if target_id in with_rh and source_id in with_rh:
        raise ConflictError(
            f"REFUS de fusion : les personnes #{target_id} et #{source_id} "
            "ont chacune une fiche RH distincte.",
        )
    if source_id in with_rh:
        return source_id, target_id
    return target_id, source_id


_EXCLUSION_STRENGTH = {
    None: 0,
    PersonExclusion.OUT_OF_PERIMETER: 1,
    PersonExclusion.NOT_A_PERSON: 2,
}


def merged_exclusion(
    target: PersonExclusion | None, source: PersonExclusion | None
) -> PersonExclusion | None:
    """Exclusion de la personne fusionnée : `not_a_person` l'emporte sur `out_of_perimeter`, qui l'emporte sur l'absence d'exclusion."""
    return max(target, source, key=_EXCLUSION_STRENGTH.__getitem__)
