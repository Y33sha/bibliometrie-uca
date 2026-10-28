"""Types et rôles des identifiants de `source_record_identifiers`."""

from enum import StrEnum


class SourceIdentifierType(StrEnum):
    """Type d'un identifiant d'enregistrement source."""

    DOI = "doi"
    HAL_ID = "hal_id"
    NNT = "nnt"
    PMID = "pmid"
    PMCID = "pmcid"
    ARXIV_ID = "arxiv_id"
    ISBN = "isbn"
    EISBN = "eisbn"


class SourceIdentifierRole(StrEnum):
    """Rôle d'un identifiant dans un enregistrement source."""

    PRIMARY = "primary"
    """Identifiant de l'enregistrement dans la source."""
    DERIVED = "derived"
    """Identifiant de l'enregistrement d'une autre source dont la source tire le sien. Un enregistrement source a au plus un identifiant dérivé."""
    SECONDARY = "secondary"
    """Identifiant que la source attribue au même document."""
    RELATED = "related"
    """Identifiant d'un document lié."""
