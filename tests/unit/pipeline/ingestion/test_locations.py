"""Localisations que désignent les identifiants d'un enregistrement source (`identifier_locations`)."""

from pipeline.ingestion.common.locations import LocationFacts, identifier_locations


def test_arxiv_et_pmcid_donnent_une_copie_ouverte():
    assert identifier_locations({"arxiv_id": "2103.11769", "pmcid": "PMC1234567", "pmid": "1"}) == [
        LocationFacts(url="https://arxiv.org/abs/2103.11769", is_oa=True),
        LocationFacts(url="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/", is_oa=True),
    ]


def test_identifiant_invalide_ou_absent():
    assert identifier_locations({"arxiv_id": "pas un identifiant"}) == []
    assert identifier_locations(None) == []
