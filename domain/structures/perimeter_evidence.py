"""Indices de l'entrée d'une contribution source ou d'une publication dans le périmètre."""

from enum import StrEnum


class PerimeterEvidence(StrEnum):
    """Indice qui fait entrer une contribution source ou une publication dans le périmètre. Reflet du type PostgreSQL `perimeter_evidence`."""

    ADDRESS = "address"
    """Une adresse de la contribution source est rattachée à une structure du périmètre."""
    HR_RECORD = "hr_record"
    """La contribution source contient l'identifiant fort d'une personne qui a une fiche RH, et la publication paraît pendant son contrat."""
    HAL_STRUCTURE = "hal_structure"
    """Une structure HAL directe de la contribution source, ou un de ses parents HAL, correspond à une structure du périmètre."""
    ROR = "ror"
    """La contribution source, sans adresse, a le ROR d'une structure du périmètre."""
    THESIS_INSTITUTION = "thesis_institution"
    """Indice d'une publication : la thèse est soutenue dans un établissement du périmètre (PPN de l'établissement de soutenance parmi les `api_ids.theses`)."""
    THESIS_PARTNER = "thesis_partner"
    """Un laboratoire partenaire de la thèse, reconnu par son PPN IdRef, est une structure du périmètre. Rattache la contribution source du doctorant."""
