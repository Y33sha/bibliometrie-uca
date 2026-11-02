"""Structures du référentiel HAL (`ref/structure`), référentiel externe des structures.

Chaque période d'une structure a sa fiche, avec ses dates de validité ; l'ancienne passe au statut `OLD`. Une fiche en double est fondue dans une structure conservée, qui la liste dans ses alias.
"""

from enum import StrEnum


class HalStructureStatus(StrEnum):
    """Statut d'une structure dans le référentiel HAL."""

    VALID = "VALID"
    OLD = "OLD"
    INCOMING = "INCOMING"
