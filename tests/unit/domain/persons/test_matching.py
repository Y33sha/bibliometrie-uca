"""Règles de matching des contributions à des personnes."""

from domain.persons.contributor_name import ContributorName
from domain.persons.matching import (
    IdentifiedPerson,
    NameFormDecision,
    Namesake,
    attested_full_first_names,
    compatible_namesakes,
    compatible_persons,
    decide_match_by_identifier,
    decide_name_form_outcome,
    full_namesakes,
    identifier_misplaced,
    strict_majority,
    trusted_identifier,
)


def _contribution(raw: str) -> ContributorName:
    return ContributorName(raw=raw)


def _contributions(*raws: str) -> list[ContributorName]:
    return [_contribution(raw) for raw in raws]


class TestTrustedIdentifier:
    def test_un_orcid_vaut_signal_selon_sa_source(self):
        assert trusted_identifier("orcid", "crossref")
        assert not trusted_identifier("orcid", "wos")
        assert not trusted_identifier("orcid", "scanr")

    def test_les_autres_identifiants_valent_signal_quelle_que_soit_la_source(self):
        assert trusted_identifier("idref", "scanr")
        assert trusted_identifier("hal_person_id", "hal")


class TestStrictMajority:
    def test_strict_majority(self):
        assert strict_majority({"martin p": 2, "dupont j": 1}) == "martin p"

    def test_relative_majority(self):
        assert strict_majority({"a": 35, "b": 33, "c": 32}) == "a"

    def test_single_vote(self):
        assert strict_majority({"martin p": 1}) == "martin p"

    def test_tie_at_the_top(self):
        assert strict_majority({"aubert p": 1, "dupont j": 1}) is None

    def test_tie_below_the_top(self):
        assert strict_majority({"a": 3, "b": 1, "c": 1}) == "a"

    def test_no_vote(self):
        assert strict_majority({}) is None

    def test_keys_without_votes(self):
        assert strict_majority({1: 0}) is None

    def test_any_keys(self):
        assert strict_majority({1: 0, 2: 1}) == 2


class TestIdentifierMisplaced:
    def test_consensus_names_another_person(self):
        assert identifier_misplaced("t dado", "s dahbi")

    def test_consensus_names_the_source_contribution(self):
        assert not identifier_misplaced("dahbi s", "s dahbi")

    def test_spelling_variant_is_not_misplaced(self):
        assert not identifier_misplaced("mueller roman", "r muller")

    def test_no_consensus(self):
        assert not identifier_misplaced("t dado", None)


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
        """Forme de nom inconnue, création interdite (membre du jury d'une thèse, par exemple) : aucun rattachement."""
        decision = decide_name_form_outcome(None, allow_create=False)
        assert decision.action == "skip"
        assert decision.reason == "creation_not_allowed"

    def test_multiple_person_ids_overrides_allow_create(self):
        """Plusieurs personnes ont la forme de nom, création interdite : l'ambiguïté motive le refus."""
        decision = decide_name_form_outcome([42, 17], allow_create=False)
        assert decision.action == "skip"
        assert decision.reason == "ambiguous_name_form"

    def test_rejected_candidate_eliminated_disambiguates(self):
        """Deux candidates, dont une rejetée pour la publication : la contribution est rattachée à l'autre."""
        decision = decide_name_form_outcome(
            [42, 17], allow_create=True, rejected_person_ids=frozenset({17})
        )
        assert decision == NameFormDecision(action="match", person_id=42)

    def test_single_rejected_candidate_skips(self):
        """Seule candidate rejetée pour la publication : ni rattachement, ni création."""
        decision = decide_name_form_outcome(
            [42], allow_create=True, rejected_person_ids=frozenset({42})
        )
        assert decision.action == "skip"
        assert decision.reason == "all_candidates_rejected"

    def test_all_candidates_rejected_skips(self):
        decision = decide_name_form_outcome(
            [42, 17], allow_create=True, rejected_person_ids=frozenset({42, 17})
        )
        assert decision.action == "skip"
        assert decision.reason == "all_candidates_rejected"

    def test_unknown_form_single_compatible_person_matches(self):
        """Forme inconnue, une seule personne aux initiales compatibles : rattachement, pas de création."""
        decision = decide_name_form_outcome(None, allow_create=True, compatible_person_ids=[42])
        assert decision == NameFormDecision(action="match", person_id=42, reason="compatible_name")

    def test_unknown_form_several_compatible_persons_skip(self):
        decision = decide_name_form_outcome(None, allow_create=True, compatible_person_ids=[42, 17])
        assert decision == NameFormDecision(action="skip", reason="ambiguous_name_form")

    def test_unknown_form_compatible_person_rejected_skips(self):
        """La seule personne compatible est rejetée pour la publication : ni rattachement, ni création."""
        decision = decide_name_form_outcome(
            None, allow_create=True, rejected_person_ids=frozenset({42}), compatible_person_ids=[42]
        )
        assert decision == NameFormDecision(action="skip", reason="all_candidates_rejected")

    def test_known_form_ignores_compatible_persons(self):
        decision = decide_name_form_outcome([7], allow_create=True, compatible_person_ids=[42])
        assert decision == NameFormDecision(action="match", person_id=7)


class TestCompatibleNamesakes:
    def test_full_name_finds_the_reduced_person(self):
        assert compatible_namesakes("Abdellah", [Namesake(1, "Tnourji", "A.")]) == [1]

    def test_reduced_name_finds_the_compound_first_name(self):
        """« A. » prolonge « Abdul-Majeed », dont les formes à initiales donnent seulement « a m »."""
        assert compatible_namesakes("A.", [Namesake(1, "Al-Izeri", "Abdul-Majeed")]) == [1]

    def test_reduced_name_finds_every_compatible_person(self):
        namesakes = [
            Namesake(1, "Martin", "Julie"),
            Namesake(2, "Martin", "Joseph"),
            Namesake(3, "Martin", "Paul"),
        ]
        assert compatible_namesakes("J.", namesakes) == [1, 2]

    def test_initials_follow_the_order_of_the_first_name(self):
        """« H. » ne prolonge pas « Bo-Hyung » : l'initiale doit commencer le prénom."""
        assert compatible_namesakes("H.", [Namesake(1, "Lee", "Bo-Hyung")]) == []
        assert compatible_namesakes("Bo-Hyung", [Namesake(1, "Lee", "H.")]) == []

    def test_reduced_person_claimed_by_a_full_namesake_is_not_a_candidate(self):
        """« Martin Jean » est le prénom plein possible de « Martin J. » : « Julien » ne se rattache pas à « Martin J. »."""
        namesakes = [Namesake(1, "Martin", "J."), Namesake(2, "Martin", "Jean")]
        assert compatible_namesakes("Julien", namesakes) == []

    def test_conflicting_reduced_person_is_not_a_candidate(self):
        assert compatible_namesakes("Julien", [Namesake(1, "Martin", "J.", conflicting=True)]) == []

    def test_full_name_ignores_full_namesakes(self):
        """Deux prénoms pleins distincts désignent deux personnes, même à initiales communes."""
        assert compatible_namesakes("Abdellah", [Namesake(1, "Tnourji", "Abdelkader")]) == []

    def test_source_contribution_without_first_name(self):
        assert compatible_namesakes("", [Namesake(1, "Martin", "J.")]) == []


class TestCompatiblePersons:
    def test_double_family_name_without_particle(self):
        """« Florence Caldefie Chezet » : le découpage au dernier mot donne « Chezet », celui aux deux derniers mots trouve « Caldefie-Chezet F. »."""
        index = {"caldefie chezet": [Namesake(1, "Caldefie-Chezet", "F.")]}
        assert compatible_persons(_contribution("Florence Caldefie Chezet"), index) == [1]

    def test_candidates_of_every_split_add_up(self):
        index = {
            "caldefie chezet": [Namesake(1, "Caldefie-Chezet", "F.")],
            "chezet": [Namesake(2, "Chezet", "F.")],
        }
        assert compatible_persons(_contribution("Florence Caldefie Chezet"), index) == [1, 2]

    def test_comma_format_keeps_its_single_split(self):
        index = {"chezet": [Namesake(2, "Chezet", "F.")]}
        assert compatible_persons(_contribution("Caldefie Chezet, Florence"), index) == []

    def test_source_split_keeps_its_single_split(self):
        index = {"chezet": [Namesake(2, "Chezet", "F.")]}
        name = ContributorName(last_name="Caldefie Chezet", first_name="Florence")
        assert compatible_persons(name, index) == []


class TestFullNamesakes:
    def test_keeps_full_first_names_that_the_initials_open(self):
        namesakes = [
            Namesake(1, "Caillaud", "Denis M."),
            Namesake(2, "Caillaud", "D."),
            Namesake(3, "Caillaud", "Marc"),
        ]
        assert full_namesakes(("d",), namesakes) == [1]

    def test_initials_must_open_the_first_name(self):
        assert full_namesakes(("b",), [Namesake(1, "Zhang", "Xiao-Bing")]) == []


class TestAttestedFullFirstNames:
    def test_keeps_compatible_full_first_names_of_the_same_family_name(self):
        names = _contributions(
            "Abdellah Tnourji", "Tnourji, A.", "Tnourji, Abdellah", "Abdellah Dupont"
        )
        assert attested_full_first_names("Tnourji", ("a",), names) == {"abdellah": "Abdellah"}

    def test_double_family_name_without_comma(self):
        names = _contributions("Florence Caldefie Chezet")
        assert attested_full_first_names("Caldefie-Chezet", ("f",), names) == {
            "florence": "Florence"
        }

    def test_incompatible_first_name_is_ignored(self):
        assert attested_full_first_names("Tnourji", ("a",), _contributions("Karim Tnourji")) == {}

    def test_most_frequent_spelling_wins(self):
        names = _contributions("Stephane Monteil", "Stéphane Monteil", "Stéphane Monteil")
        assert attested_full_first_names("Monteil", ("s",), names) == {"stephane": "Stéphane"}

    def test_several_distinct_first_names(self):
        names = _contributions("Jean Martin", "Julien Martin")
        assert attested_full_first_names("Martin", ("j",), names).keys() == {"jean", "julien"}


class TestDecideMatchByIdentifier:
    def test_compatible_name_returns_person_id(self):
        idref_map = {"252404955": IdentifiedPerson(42, "dupont", "jean")}
        result = decide_match_by_identifier(
            "252404955", idref_map, _contribution("Jean Dupont"), ("jean dupont",), {}
        )
        assert result.person_id == 42
        assert result.rejection is None

    def test_incompatible_name_rejected(self):
        """Sans verdict sur la forme de nom, un nom incompatible fait refuser le rattachement, et le rejet est renvoyé."""
        idref_map = {"252404955": IdentifiedPerson(42, "dupont", "jean")}
        result = decide_match_by_identifier(
            "252404955", idref_map, _contribution("Paul Martin"), ("paul martin",), {}
        )
        assert result.person_id is None
        assert result.rejection == (42, "jean dupont")

    def test_confirmed_name_form_matches_without_token_test(self):
        """Une forme de nom confirmée pour la personne la rattache, même à tokens incompatibles (changement de nom : « Van Lander » confirmée pour « Maneval »)."""
        idref_map = {"x": IdentifiedPerson(42, "maneval", "axelle")}
        status = {("van lander axelle", 42): "confirmed"}
        result = decide_match_by_identifier(
            "x", idref_map, _contribution("Van Lander Axelle"), ("van lander axelle",), status
        )
        assert result.person_id == 42
        assert result.rejection is None

    def test_rejected_name_form_refused_even_if_compatible(self):
        """Une forme de nom rejetée pour la personne fait refuser le rattachement, même à tokens compatibles."""
        idref_map = {"x": IdentifiedPerson(42, "dupont", "jean")}
        status = {("jean dupont", 42): "rejected"}
        result = decide_match_by_identifier(
            "x", idref_map, _contribution("Jean Dupont"), ("jean dupont",), status
        )
        assert result.person_id is None
        assert result.rejection == (42, "jean dupont")

    def test_value_absent_returns_empty(self):
        idref_map = {"252404955": IdentifiedPerson(42, "dupont", "jean")}
        result = decide_match_by_identifier("999999999", idref_map, _contribution("X"), ("x",), {})
        assert result.person_id is None
        assert result.rejection is None

    def test_falsy_value_returns_empty(self):
        """Une valeur vide ou `None` laisse la contribution sans rattachement."""
        m = {"foo": IdentifiedPerson(1, "a", "b")}
        assert decide_match_by_identifier(None, m, _contribution("X"), ("x",), {}).person_id is None
        assert decide_match_by_identifier("", m, _contribution("X"), ("x",), {}).person_id is None

    def test_empty_map(self):
        assert (
            decide_match_by_identifier("anything", {}, _contribution("X"), ("x",), {}).person_id
            is None
        )

    def test_surname_only_source_contribution_not_rejected(self):
        """Contribution source réduite au nom de famille : ses tokens sont un sous-ensemble du nom de la personne, donc compatibles."""
        idref_map = {"x": IdentifiedPerson(42, "dupont", "jean")}
        result = decide_match_by_identifier(
            "x", idref_map, _contribution("Dupont"), ("dupont",), {}
        )
        assert result.person_id == 42
        assert result.rejection is None

    def test_works_for_orcid_too(self):
        """Même règle pour un ORCID que pour un IdRef."""
        orcid_map = {"0000-0001-2345-6789": IdentifiedPerson(7, "curie", "marie")}
        result = decide_match_by_identifier(
            "0000-0001-2345-6789", orcid_map, _contribution("Marie Curie"), ("marie curie",), {}
        )
        assert result.person_id == 7

    def test_graphie_variant_corroborates(self):
        """Une graphie proche de celle de la personne (faute de frappe) confirme le rattachement."""
        idref_map = {"x": IdentifiedPerson(42, "khalil", "toufik")}
        result = decide_match_by_identifier(
            "x", idref_map, _contribution("Toufic Khalil"), ("toufic khalil",), {}
        )
        assert result.person_id == 42
        assert result.rejection is None

    def test_surname_homonym_still_rejected(self):
        """Même nom de famille, prénom franchement autre : le rattachement est refusé."""
        idref_map = {"x": IdentifiedPerson(42, "chanal", "helene")}
        result = decide_match_by_identifier(
            "x", idref_map, _contribution("Herve Chanal"), ("herve chanal",), {}
        )
        assert result.person_id is None
        assert result.rejection == (42, "helene chanal")

    def test_verdict_on_inverted_form(self):
        """Contribution source au nom et prénom inversés : le verdict de sa forme « nom prénom » tranche."""
        idref_map = {"x": IdentifiedPerson(42, "dupont", "jean")}
        status = {("jean dupont", 42): "rejected"}
        result = decide_match_by_identifier(
            "x", idref_map, _contribution("Dupont Jean"), ("dupont jean", "jean dupont"), status
        )
        assert result.person_id is None
