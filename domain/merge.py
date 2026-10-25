"""Fusion de deux entités : nature des données rattachées à une entité, et entités dont l'identifiant absorbé redirige.

Chaque étape de fusion d'une entité (`MergeStep`) déclare la nature de sa donnée. Un test confronte ces étapes au schéma de la base.
"""

from enum import StrEnum


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
    SERIAL = "serial"
    PUBLISHER = "publisher"
    MONOGRAPH = "monograph"
    PUBLICATION = "publication"
