"""Fusion de deux entités."""

from enum import StrEnum


class DataNature(StrEnum):
    """Origine d'une donnée rattachée à une entité."""

    DECISION = "decision"
    """Saisie à la main."""
    DERIVED = "derived"
    """Calculée par le pipeline ou importée."""
    MIXED = "mixed"
    """Saisie à la main ou dérivée selon la ligne : un statut, une origine ou une trace d'édition les distingue."""


class MergedEntity(StrEnum):
    """Entité fusionnable dont l'identifiant absorbé redirige vers l'identifiant conservé."""

    PERSON = "person"
    SERIAL = "serial"
    PUBLISHER = "publisher"
    MONOGRAPH = "monograph"
    PUBLICATION = "publication"
