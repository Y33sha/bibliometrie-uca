"""Fusion de deux entités."""

from enum import StrEnum


class MergedEntity(StrEnum):
    """Entité fusionnable dont l'identifiant absorbé redirige vers l'identifiant conservé."""

    PERSON = "person"
    SERIAL = "serial"
    PUBLISHER = "publisher"
    MONOGRAPH = "monograph"
    PUBLICATION = "publication"
