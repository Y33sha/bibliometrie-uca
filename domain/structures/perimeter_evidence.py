"""Indices de l'entrée d'une signature ou d'une publication dans le périmètre."""

from enum import StrEnum


class PerimeterEvidence(StrEnum):
    """Indice qui fait entrer une signature ou une publication dans le périmètre. Reflet du type PostgreSQL `perimeter_evidence`."""

    # Une adresse de la signature est rattachée à une structure du périmètre.
    ADDRESS = "address"
    # La signature contient l'identifiant fort d'une personne RH, et le document paraît pendant son contrat.
    HR_RECORD = "hr_record"
    # Une structure HAL directe de la signature, ou un de ses parents HAL, correspond à une structure du périmètre.
    HAL_STRUCTURE = "hal_structure"
    # Un ROR de la signature est celui d'une structure du périmètre.
    ROR = "ror"
    # Indice d'une publication : la thèse est soutenue dans un établissement du périmètre (PPN de l'établissement de soutenance parmi les `api_ids.theses`).
    THESIS_INSTITUTION = "thesis_institution"
    # Un laboratoire partenaire de la thèse, reconnu par son PPN IdRef, est une structure du périmètre. Rattache la signature du doctorant.
    THESIS_PARTNER = "thesis_partner"
