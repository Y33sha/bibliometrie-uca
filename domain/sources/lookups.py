"""Vocabulaire de la table `failed_lookups`."""

from domain.source_records.identifiers import SourceIdentifierType

LOOKUP_ID_TYPES = (
    SourceIdentifierType.DOI,
    SourceIdentifierType.HAL_ID,
    SourceIdentifierType.NNT,
    SourceIdentifierType.PATENT_PUBLICATION_NUMBER,
    SourceIdentifierType.PATENT_APPLICATION_NUMBER,
)
"""Types d'identifiants cherchés par la phase `fetch_missing`, valeurs de `failed_lookups.id_type`."""
