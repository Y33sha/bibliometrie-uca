"""Indices de l'entrée d'une contribution source ou d'une publication dans le périmètre."""

from enum import StrEnum


class PerimeterEvidence(StrEnum):
    """Indice qui fait entrer une contribution source ou une publication dans le périmètre. Reflet du type PostgreSQL `perimeter_evidence`."""

    # Une adresse de la contribution source est rattachée à une structure du périmètre.
    ADDRESS = "address"
    # La contribution source contient l'identifiant fort d'une personne qui a une fiche RH, et la publication paraît pendant son contrat.
    HR_RECORD = "hr_record"
    # Une structure HAL directe de la contribution source, ou un de ses parents HAL, correspond à une structure du périmètre.
    HAL_STRUCTURE = "hal_structure"
    # Un ROR sans adresse de la contribution source est celui d'une structure du périmètre.
    ROR = "ror"
    # Indice d'une publication : la thèse est soutenue dans un établissement du périmètre (PPN de l'établissement de soutenance parmi les `api_ids.theses`).
    THESIS_INSTITUTION = "thesis_institution"
    # Un laboratoire partenaire de la thèse, reconnu par son PPN IdRef, est une structure du périmètre. Rattache la contribution source du doctorant.
    THESIS_PARTNER = "thesis_partner"
