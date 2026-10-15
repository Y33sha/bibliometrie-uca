"""Indices de l'entrée d'une signature ou d'une publication dans le périmètre."""

from enum import StrEnum


class PerimeterEvidence(StrEnum):
    """Indice qui fait entrer une signature dans le périmètre. Reflet du type PostgreSQL `perimeter_evidence`."""

    # Une adresse de la signature est rattachée à une structure du périmètre.
    ADDRESS = "address"
    # La signature contient l'identifiant fort d'une personne RH, et le document paraît pendant son contrat.
    RH_IDENTITY = "rh_identity"
