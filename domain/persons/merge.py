"""Fusion de deux personnes : rôles, données d'une personne et règle de fusion de chacune.

`PERSON_DATA` recense tout ce qui s'attache à une personne. La fusion applique la règle de chaque donnée ; un test confronte le recensement au schéma de la base.
"""

from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum

from domain.errors import ConflictError
from domain.persons.person import PersonExclusion


class MergeRule(StrEnum):
    """Sort d'une donnée de la personne absorbée."""

    # Rattachée à la personne conservée.
    TRANSFER = "transfer"
    # Rattachée à la personne conservée, sauf si celle-ci a déjà la même.
    TRANSFER_UNIQUE = "transfer_unique"
    # Combinée avec la donnée de la personne conservée, selon une règle propre.
    COMBINE = "combine"
    # La personne conservée garde la sienne ; celle de l'absorbée est perdue.
    KEEP_TARGET = "keep_target"
    # La personne absorbée n'en a jamais : la personne qui en a une est conservée (`merge_roles`).
    ABSENT_FROM_SOURCE = "absent_from_source"


class DataNature(StrEnum):
    """Origine d'une donnée."""

    # Posée par l'administration.
    DECISION = "decision"
    # Calculée par le pipeline ou importée.
    DERIVED = "derived"
    # Décision ou donnée dérivée selon la ligne : statut, origine, édition.
    MIXED = "mixed"


@dataclass(frozen=True, slots=True)
class PersonData:
    rule: MergeRule
    nature: DataNature
    description: str


PERSON_DATA: dict[str, PersonData] = {
    "signatures": PersonData(
        MergeRule.TRANSFER, DataNature.DERIVED, "Signatures rattachées à la personne."
    ),
    "authorships": PersonData(
        MergeRule.TRANSFER_UNIQUE,
        DataNature.DERIVED,
        "Authorships, une par publication.",
    ),
    "rejected_authorships": PersonData(
        MergeRule.TRANSFER_UNIQUE,
        DataNature.DECISION,
        "Rejets d'une paire publication-personne, un par publication.",
    ),
    "confirmed_signatures": PersonData(
        MergeRule.TRANSFER,
        DataNature.DECISION,
        "Confirmations d'une signature.",
    ),
    "distinct_persons": PersonData(
        MergeRule.COMBINE,
        DataNature.DECISION,
        "Non-doublons. Ceux de l'absorbée passent à la conservée ; celui qui oppose les deux personnes fusionnées est supprimé.",
    ),
    "identifiers": PersonData(
        MergeRule.TRANSFER,
        DataNature.MIXED,
        "Identifiants et leur statut.",
    ),
    "name_forms": PersonData(
        MergeRule.COMBINE,
        DataNature.MIXED,
        "Formes de nom et leur statut. Sur une forme commune, le statut de la conservée l'emporte, sauf s'il est en attente.",
    ),
    "rh_record": PersonData(
        MergeRule.ABSENT_FROM_SOURCE,
        DataNature.DERIVED,
        "Fiche de l'annuaire RH.",
    ),
    "name": PersonData(
        MergeRule.KEEP_TARGET,
        DataNature.MIXED,
        "Nom et prénom. Les formes de nom de l'absorbée restent.",
    ),
    "created_at": PersonData(MergeRule.KEEP_TARGET, DataNature.DERIVED, "Date de création."),
    "exclusion": PersonData(
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
