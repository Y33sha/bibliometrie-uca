"""Tests des règles pures de matching d'authorships à des personnes."""

from domain.persons.matching import decide_match_by_identifier


class TestDecideMatchByIdentifier:
    def test_value_present_returns_person_id(self):
        idref_map = {"252404955": 42, "11111111X": 17}
        assert decide_match_by_identifier("252404955", idref_map) == 42

    def test_value_absent_returns_none(self):
        assert decide_match_by_identifier("999999999", {"252404955": 42}) is None

    def test_falsy_value_returns_none(self):
        """Pas de tentative de lookup si la valeur est vide/None."""
        assert decide_match_by_identifier(None, {"foo": 1}) is None
        assert decide_match_by_identifier("", {"foo": 1}) is None

    def test_empty_map(self):
        assert decide_match_by_identifier("anything", {}) is None

    def test_works_for_orcid_too(self):
        """La fonction est générique : même contrat pour IdRef et ORCID."""
        orcid_map = {"0000-0001-2345-6789": 7}
        assert decide_match_by_identifier("0000-0001-2345-6789", orcid_map) == 7
