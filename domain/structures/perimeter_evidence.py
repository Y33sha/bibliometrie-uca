"""Indices d'appartenance au périmètre d'une contribution source ou d'une publication."""

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
    PATENT_APPLICANT = "patent_applicant"
    """Un déposant de la famille de brevets, reconnu par la forme de comparaison de son nom parmi les graphies de `api_ids.ops`, est une structure du périmètre. Rattache toutes les contributions sources de la famille."""


DOCUMENT_EVIDENCE: frozenset[PerimeterEvidence] = frozenset(
    {PerimeterEvidence.THESIS_INSTITUTION, PerimeterEvidence.PATENT_APPLICANT}
)
"""Indices d'appartenance au périmètre liés au document : thèse soutenue ou brevet déposé par une structure du périmètre. Les autres indices sont liés à une contribution. Un indice lié au document va à toutes les contributions sources de l'enregistrement source, quel que soit leur rôle. La publication entre dans le périmètre, même sans contribution rattachée à une personne."""
