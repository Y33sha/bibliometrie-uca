"""Fusion de deux entités : règle de fusion et nature de chaque donnée rattachée à une entité.

Chaque entité fusionnable recense ses données dans un dictionnaire `nom → MergedData` (`domain.persons.merge.PERSON_DATA`, `domain.journals.merge.JOURNAL_DATA`). La fusion applique la règle de chaque donnée ; un test confronte le recensement au schéma de la base.
"""

from dataclasses import dataclass
from enum import StrEnum


class MergeRule(StrEnum):
    """Sort d'une donnée de l'entité absorbée."""

    # Rattachée à l'entité conservée.
    TRANSFER = "transfer"
    # Rattachée à l'entité conservée, sauf si celle-ci a déjà la même.
    TRANSFER_UNIQUE = "transfer_unique"
    # Combinée avec la donnée de l'entité conservée, selon une règle propre.
    COMBINE = "combine"
    # L'entité conservée garde sa valeur ; sans valeur, elle prend celle de l'absorbée.
    FILL_EMPTY = "fill_empty"
    # L'entité conservée garde la sienne ; celle de l'absorbée est perdue.
    KEEP_TARGET = "keep_target"
    # Celle de l'absorbée est perdue ; le pipeline recalcule celle de l'entité conservée.
    RECOMPUTED = "recomputed"
    # L'entité absorbée n'en a jamais : l'entité qui en a une est conservée.
    ABSENT_FROM_SOURCE = "absent_from_source"


class DataNature(StrEnum):
    """Origine d'une donnée."""

    # Posée par l'administration.
    DECISION = "decision"
    # Calculée par le pipeline ou importée.
    DERIVED = "derived"
    # Décision ou donnée dérivée selon la ligne ou la valeur : statut, origine, édition.
    MIXED = "mixed"


class MergedEntity(StrEnum):
    """Entité fusionnable dont l'identifiant absorbé redirige vers l'identifiant conservé."""

    PERSON = "person"
    JOURNAL = "journal"
    PUBLISHER = "publisher"
    MONOGRAPH = "monograph"
    PUBLICATION = "publication"


@dataclass(frozen=True, slots=True)
class MergedData:
    rule: MergeRule
    nature: DataNature
    description: str
