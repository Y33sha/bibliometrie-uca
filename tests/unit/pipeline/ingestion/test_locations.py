"""Localisations désignées par les identifiants d'un enregistrement source (`identifier_locations`)."""

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from pipeline.ingestion.common.locations import LocationFacts, identifier_locations


def _id(id_type, value):
    return SourceIdentifier(id_type, value, SourceIdentifierRole.SECONDARY)


def test_arxiv_et_pmcid_donnent_une_copie_ouverte():
    identifiers = [
        _id(SourceIdentifierType.ARXIV_ID, "2103.11769"),
        _id(SourceIdentifierType.PMCID, "PMC1234567"),
        _id(SourceIdentifierType.PMID, "1"),
    ]
    assert identifier_locations(identifiers) == [
        LocationFacts(url="https://arxiv.org/abs/2103.11769", is_oa=True),
        LocationFacts(url="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/", is_oa=True),
    ]


def test_identifiant_invalide_ou_absent():
    assert identifier_locations([_id(SourceIdentifierType.ARXIV_ID, "pas un identifiant")]) == []
    assert identifier_locations([]) == []
