"""Identifiants qui désignent le même document chez OpenAlex et INSPIRE-HEP (`domain.source_records.inspire_author_lists`)."""

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.source_records.inspire_author_lists import document_keys


def test_doi_hal_id_et_cds_hors_identifiants_lies():
    secondary, related = SourceIdentifierRole.SECONDARY, SourceIdentifierRole.RELATED
    identifiers = [
        SourceIdentifier(SourceIdentifierType.DOI, "10.1/a", SourceIdentifierRole.DERIVED),
        SourceIdentifier(SourceIdentifierType.DOI, "10.1/erratum", related),
        SourceIdentifier(SourceIdentifierType.HAL_ID, "hal-01", secondary),
        SourceIdentifier(SourceIdentifierType.CDS, "2838028", secondary),
        SourceIdentifier(SourceIdentifierType.PMID, "123", secondary),
    ]
    assert document_keys(identifiers) == {
        (SourceIdentifierType.DOI, "10.1/a"),
        (SourceIdentifierType.HAL_ID, "hal-01"),
        (SourceIdentifierType.CDS, "2838028"),
    }
