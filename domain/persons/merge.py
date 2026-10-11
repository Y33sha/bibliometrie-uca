"""Fusion de deux personnes : rôles, et données d'une personne avec leur règle de fusion (`PERSON_DATA`)."""

from collections.abc import Collection

from domain.errors import ConflictError
from domain.merge import DataNature, MergedData, MergeRule
from domain.persons.person import PersonExclusion

PERSON_DATA: dict[str, MergedData] = {
    "signatures": MergedData(
        MergeRule.TRANSFER, DataNature.DERIVED, "Signatures rattachées à la personne."
    ),
    "authorships": MergedData(
        MergeRule.TRANSFER_UNIQUE,
        DataNature.DERIVED,
        "Authorships, une par publication.",
    ),
    "rejected_authorships": MergedData(
        MergeRule.TRANSFER_UNIQUE,
        DataNature.DECISION,
        "Rejets d'une paire publication-personne, un par publication.",
    ),
    "confirmed_signatures": MergedData(
        MergeRule.TRANSFER,
        DataNature.DECISION,
        "Confirmations d'une signature.",
    ),
    "distinct_persons": MergedData(
        MergeRule.COMBINE,
        DataNature.DECISION,
        "Non-doublons. Ceux de l'absorbée passent à la conservée ; celui qui oppose les deux personnes fusionnées est supprimé.",
    ),
    "identifiers": MergedData(
        MergeRule.TRANSFER,
        DataNature.MIXED,
        "Identifiants et leur statut.",
    ),
    "name_forms": MergedData(
        MergeRule.COMBINE,
        DataNature.MIXED,
        "Formes de nom et leur statut. Sur une forme commune, le statut de la conservée l'emporte, sauf s'il est en attente.",
    ),
    "rh_record": MergedData(
        MergeRule.ABSENT_FROM_SOURCE,
        DataNature.DERIVED,
        "Fiche de l'annuaire RH.",
    ),
    "name": MergedData(
        MergeRule.KEEP_TARGET,
        DataNature.MIXED,
        "Nom et prénom. Les formes de nom de l'absorbée restent.",
    ),
    "created_at": MergedData(MergeRule.KEEP_TARGET, DataNature.DERIVED, "Date de création."),
    "exclusion": MergedData(
        MergeRule.COMBINE,
        DataNature.DECISION,
        "Exclusion. La plus forte des deux l'emporte (`merged_exclusion`).",
    ),
}


def merge_roles(target_id: int, source_id: int, *, with_rh: Collection[int]) -> tuple[int, int]:
    """Rôles (conservée, absorbée) d'une fusion demandée `target ← source`.

    Une personne qui a une fiche RH est toujours conservée : si seule la source en a une, les rôles s'inversent. `with_rh` contient les ids des personnes qui ont une fiche RH.

    Lève `ConflictError` si les deux personnes ont chacune une fiche RH.
    """
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
