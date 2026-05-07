"""Tests des règles pures de matching d'authorships à des personnes."""

from domain.persons.matching import (
    NameFormDecision,
    decide_match_by_identifier,
    decide_name_form_outcome,
)


class TestDecideNameFormOutcome:
    def test_single_person_id_matches(self):
        decision = decide_name_form_outcome([42], allow_create=True)
        assert decision == NameFormDecision(action="match", person_id=42)

    def test_multiple_person_ids_skip_ambiguous(self):
        decision = decide_name_form_outcome([42, 17], allow_create=True)
        assert decision.action == "skip"
        assert decision.reason == "ambiguous_name_form"
        assert decision.person_id is None

    def test_no_match_with_allow_create(self):
        decision = decide_name_form_outcome(None, allow_create=True)
        assert decision == NameFormDecision(action="create")

    def test_no_match_without_allow_create_skips(self):
        """Cas typique : rôle non-auteur d'une thèse, person inconnue."""
        decision = decide_name_form_outcome(None, allow_create=False)
        assert decision.action == "skip"
        assert decision.reason == "creation_not_allowed"

    def test_multiple_person_ids_overrides_allow_create(self):
        """Ambiguïté de nom → skip même si la création est autorisée
        (on ne crée pas une personne quand des homonymes existent)."""
        decision = decide_name_form_outcome([42, 17], allow_create=False)
        assert decision.action == "skip"
        assert decision.reason == "ambiguous_name_form"


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
