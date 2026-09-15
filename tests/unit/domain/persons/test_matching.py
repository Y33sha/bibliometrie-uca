"""Tests des règles pures de matching d'authorships à des personnes."""

from domain.persons.matching import (
    IdentifiedPerson,
    NameFormDecision,
    Namesake,
    PersonMatchDecision,
    attested_full_first_names,
    compatible_namesakes,
    consensus_name,
    decide_cross_source_match,
    decide_match_by_identifier,
    decide_name_form_outcome,
    decide_person_match,
    form_matches_person,
    identifier_misplaced,
)


class TestConsensusName:
    def test_strict_majority(self):
        assert consensus_name({"martin p": 2, "dupont j": 1}) == "martin p"

    def test_relative_majority(self):
        assert consensus_name({"a": 35, "b": 33, "c": 32}) == "a"

    def test_single_vote(self):
        assert consensus_name({"martin p": 1}) == "martin p"

    def test_tie_at_the_top(self):
        assert consensus_name({"aubert p": 1, "dupont j": 1}) is None

    def test_tie_below_the_top(self):
        assert consensus_name({"a": 3, "b": 1, "c": 1}) == "a"

    def test_no_vote(self):
        assert consensus_name({}) is None


class TestIdentifierMisplaced:
    def test_consensus_names_another_person(self):
        assert identifier_misplaced("t dado", "s dahbi")

    def test_consensus_names_the_signature(self):
        assert not identifier_misplaced("dahbi s", "s dahbi")

    def test_spelling_variant_is_not_misplaced(self):
        assert not identifier_misplaced("mueller roman", "r muller")

    def test_no_consensus(self):
        assert not identifier_misplaced("t dado", None)


class TestFormMatchesPerson:
    def test_matches_canonical_name(self):
        assert form_matches_person("helene chanal", "chanal", "helene")

    def test_matches_via_confirmed_form(self):
        # Le consensus colle à une forme confirmée, que le nom-prénom canonique ne recouvre pas.
        assert form_matches_person(
            "pierre michel llorca", "llorca", "pm", confirmed_forms=["pierre michel llorca"]
        )

    def test_homonym_does_not_match(self):
        # Même patronyme, prénoms distincts : « hervé » ≠ « hélène ».
        assert not form_matches_person("herve chanal", "chanal", "helene")

    def test_unrelated_confirmed_form_does_not_match(self):
        assert not form_matches_person(
            "helene chanal", "chanal", "herve", confirmed_forms=["herve chanal"]
        )

    def test_family_name_alone_matches(self):
        assert form_matches_person("martin", "martin", "jean")

    def test_first_name_of_another_person_does_not_match(self):
        """Le prénom commun ne suffit pas : le patronyme de la forme doit aussi correspondre."""
        assert not form_matches_person("pierre durand", "martin", "pierre")

    def test_confirmed_form_longer_than_the_form(self):
        assert form_matches_person("dupont", "martin", "jean", confirmed_forms=["marie dupont"])

    def test_form_longer_than_the_confirmed_form(self):
        assert form_matches_person(
            "marie jeanne dupont", "martin", "paul", confirmed_forms=["marie dupont"]
        )


class TestDecideCrossSourceMatch:
    def test_no_candidates_returns_none(self):
        assert (
            decide_cross_source_match(
                authorship_source="openalex",
                last_norm="dupont",
                first_norm="jean",
                candidates=[],
            )
            is None
        )

    def test_single_compatible_candidate(self):
        candidates = [(42, "dupont", "jean", "hal")]
        assert (
            decide_cross_source_match(
                authorship_source="openalex",
                last_norm="dupont",
                first_norm="jean",
                candidates=candidates,
            )
            == 42
        )

    def test_same_source_candidates_skipped(self):
        """Les candidats portant la même source que l'authorship sont
        ignorés (ils ne portent aucun signal nouveau)."""
        candidates = [(42, "dupont", "jean", "openalex")]
        assert (
            decide_cross_source_match(
                authorship_source="openalex",
                last_norm="dupont",
                first_norm="jean",
                candidates=candidates,
            )
            is None
        )

    def test_incompatible_name_skipped(self):
        candidates = [(42, "martin", "paul", "hal")]
        assert (
            decide_cross_source_match(
                authorship_source="openalex",
                last_norm="dupont",
                first_norm="jean",
                candidates=candidates,
            )
            is None
        )

    def test_same_source_candidate_does_not_hide_the_next_one(self):
        candidates = [(17, "dupont", "jean", "openalex"), (42, "dupont", "jean", "hal")]
        assert (
            decide_cross_source_match(
                authorship_source="openalex",
                last_norm="dupont",
                first_norm="jean",
                candidates=candidates,
            )
            == 42
        )

    def test_same_first_name_other_last_name_skipped(self):
        assert (
            decide_cross_source_match(
                authorship_source="openalex",
                last_norm="dupont",
                first_norm="jean",
                candidates=[(42, "martin", "jean", "hal")],
            )
            is None
        )

    def test_same_last_name_other_first_name_skipped(self):
        assert (
            decide_cross_source_match(
                authorship_source="openalex",
                last_norm="dupont",
                first_norm="jean",
                candidates=[(42, "dupont", "pierre", "hal")],
            )
            is None
        )

    def test_multiple_compatible_same_pid_returns_pid(self):
        """Plusieurs candidats compatibles qui pointent tous vers la même
        person_id → match safe."""
        candidates = [
            (42, "dupont", "jean", "hal"),
            (42, "dupont", "j", "wos"),
        ]
        assert (
            decide_cross_source_match(
                authorship_source="openalex",
                last_norm="dupont",
                first_norm="jean",
                candidates=candidates,
            )
            == 42
        )

    def test_multiple_compatible_different_pids_returns_none(self):
        """Conflit : >1 person_id distincts compatibles → pas de match."""
        candidates = [
            (42, "dupont", "jean", "hal"),
            (17, "dupont", "j", "wos"),
        ]
        assert (
            decide_cross_source_match(
                authorship_source="openalex",
                last_norm="dupont",
                first_norm="jean",
                candidates=candidates,
            )
            is None
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

    def test_rejected_candidate_eliminated_disambiguates(self):
        """2 candidats dont 1 rejeté pour la publi → l'élimination ne laisse
        qu'une candidate → match univoque (désambiguïsation par élimination)."""
        decision = decide_name_form_outcome(
            [42, 17], allow_create=True, rejected_person_ids=frozenset({17})
        )
        assert decision == NameFormDecision(action="match", person_id=42)

    def test_single_rejected_candidate_skips(self):
        """Unique candidate rejetée pour la publi → orpheline, pas de match,
        pas de création (on ne crée pas une personne pour une paire rejetée)."""
        decision = decide_name_form_outcome(
            [42], allow_create=True, rejected_person_ids=frozenset({42})
        )
        assert decision.action == "skip"
        assert decision.reason == "ambiguous_name_form"

    def test_all_candidates_rejected_skips(self):
        decision = decide_name_form_outcome(
            [42, 17], allow_create=True, rejected_person_ids=frozenset({42, 17})
        )
        assert decision.action == "skip"
        assert decision.reason == "ambiguous_name_form"

    def test_unknown_form_single_compatible_person_matches(self):
        """Forme inconnue, une seule personne aux initiales compatibles : rattachement, pas de création."""
        decision = decide_name_form_outcome(None, allow_create=True, compatible_person_ids=[42])
        assert decision == NameFormDecision(action="match", person_id=42, reason="compatible_name")

    def test_unknown_form_several_compatible_persons_skip(self):
        decision = decide_name_form_outcome(None, allow_create=True, compatible_person_ids=[42, 17])
        assert decision == NameFormDecision(action="skip", reason="ambiguous_name_form")

    def test_unknown_form_compatible_person_rejected_skips(self):
        """La seule personne compatible est rejetée pour la publication : orpheline, pas de création."""
        decision = decide_name_form_outcome(
            None, allow_create=True, rejected_person_ids=frozenset({42}), compatible_person_ids=[42]
        )
        assert decision == NameFormDecision(action="skip", reason="ambiguous_name_form")

    def test_known_form_ignores_compatible_persons(self):
        decision = decide_name_form_outcome([7], allow_create=True, compatible_person_ids=[42])
        assert decision == NameFormDecision(action="match", person_id=7)


class TestCompatibleNamesakes:
    def test_full_signature_finds_the_reduced_person(self):
        assert compatible_namesakes("Abdellah", [Namesake(1, "Tnourji", "A.")]) == [1]

    def test_reduced_signature_finds_the_compound_first_name(self):
        """« A. » prolonge « Abdul-Majeed », dont les formes à initiales ne donnent que « a m »."""
        assert compatible_namesakes("A.", [Namesake(1, "Al-Izeri", "Abdul-Majeed")]) == [1]

    def test_reduced_signature_finds_every_compatible_person(self):
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
        """« Martin J. » a déjà son prénom plein possible, « Martin Jean » : « Julien » ne s'y rattache pas."""
        namesakes = [Namesake(1, "Martin", "J."), Namesake(2, "Martin", "Jean")]
        assert compatible_namesakes("Julien", namesakes) == []

    def test_conflicting_reduced_person_is_not_a_candidate(self):
        assert compatible_namesakes("Julien", [Namesake(1, "Martin", "J.", conflicting=True)]) == []

    def test_full_signature_ignores_full_namesakes(self):
        """Deux prénoms pleins distincts désignent deux personnes, même à initiales communes."""
        assert compatible_namesakes("Abdellah", [Namesake(1, "Tnourji", "Abdelkader")]) == []

    def test_signature_without_first_name(self):
        assert compatible_namesakes("", [Namesake(1, "Martin", "J.")]) == []


class TestAttestedFullFirstNames:
    def test_keeps_compatible_full_first_names_of_the_same_family_name(self):
        names = ["Abdellah Tnourji", "Tnourji, A.", "Tnourji, Abdellah", "Abdellah Dupont"]
        assert attested_full_first_names("Tnourji", ("a",), names) == {"abdellah": "Abdellah"}

    def test_incompatible_first_name_is_ignored(self):
        assert attested_full_first_names("Tnourji", ("a",), ["Karim Tnourji"]) == {}

    def test_most_frequent_spelling_wins(self):
        names = ["Stephane Monteil", "Stéphane Monteil", "Stéphane Monteil"]
        assert attested_full_first_names("Monteil", ("s",), names) == {"stephane": "Stéphane"}

    def test_several_distinct_first_names(self):
        names = ["Jean Martin", "Julien Martin"]
        assert attested_full_first_names("Martin", ("j",), names).keys() == {"jean", "julien"}


class TestDecideMatchByIdentifier:
    def test_compatible_name_returns_person_id(self):
        idref_map = {"252404955": IdentifiedPerson(42, "dupont", "jean")}
        result = decide_match_by_identifier(
            "252404955", idref_map, "Jean Dupont", "jean dupont", {}
        )
        assert result.person_id == 42
        assert result.rejection is None

    def test_incompatible_name_rejected(self):
        """Sans verdict, nom incompatible → match refusé (test de tokens), rejet journalisé."""
        idref_map = {"252404955": IdentifiedPerson(42, "dupont", "jean")}
        result = decide_match_by_identifier(
            "252404955", idref_map, "Paul Martin", "paul martin", {}
        )
        assert result.person_id is None
        assert result.rejection == (42, "jean dupont")

    def test_confirmed_name_form_matches_without_token_test(self):
        """Forme confirmée pour la personne → match même si les tokens divergeraient
        (changement de nom : « Van Lander » confirmée pour « Maneval »)."""
        idref_map = {"x": IdentifiedPerson(42, "maneval", "axelle")}
        status = {("van lander axelle", 42): "confirmed"}
        result = decide_match_by_identifier(
            "x", idref_map, "Van Lander Axelle", "van lander axelle", status
        )
        assert result.person_id == 42
        assert result.rejection is None

    def test_rejected_name_form_refused_even_if_compatible(self):
        """Forme rejetée pour la personne → refus même si les tokens seraient compatibles."""
        idref_map = {"x": IdentifiedPerson(42, "dupont", "jean")}
        status = {("jean dupont", 42): "rejected"}
        result = decide_match_by_identifier("x", idref_map, "Jean Dupont", "jean dupont", status)
        assert result.person_id is None
        assert result.rejection == (42, "jean dupont")

    def test_value_absent_returns_empty(self):
        idref_map = {"252404955": IdentifiedPerson(42, "dupont", "jean")}
        result = decide_match_by_identifier("999999999", idref_map, "X", "x", {})
        assert result.person_id is None
        assert result.rejection is None

    def test_falsy_value_returns_empty(self):
        """Pas de tentative de lookup si la valeur est vide/None."""
        m = {"foo": IdentifiedPerson(1, "a", "b")}
        assert decide_match_by_identifier(None, m, "X", "x", {}).person_id is None
        assert decide_match_by_identifier("", m, "X", "x", {}).person_id is None

    def test_empty_map(self):
        assert decide_match_by_identifier("anything", {}, "X", "x", {}).person_id is None

    def test_surname_only_signature_not_rejected(self):
        """Signature trop pauvre (nom seul) : compatible (sous-ensemble de tokens),
        donc pas de refus — on s'abstient plutôt que de rejeter."""
        idref_map = {"x": IdentifiedPerson(42, "dupont", "jean")}
        result = decide_match_by_identifier("x", idref_map, "Dupont", "dupont", {})
        assert result.person_id == 42
        assert result.rejection is None

    def test_works_for_orcid_too(self):
        """La fonction est générique : même contrat pour IdRef et ORCID."""
        orcid_map = {"0000-0001-2345-6789": IdentifiedPerson(7, "curie", "marie")}
        result = decide_match_by_identifier(
            "0000-0001-2345-6789", orcid_map, "Marie Curie", "marie curie", {}
        )
        assert result.person_id == 7

    def test_graphie_variant_corroborates(self):
        """Variante de graphie du propriétaire (faute de frappe) : corrobore et se
        rattache, au lieu d'être rejetée puis dédoublée au canal nominal."""
        idref_map = {"x": IdentifiedPerson(42, "khalil", "toufik")}
        result = decide_match_by_identifier("x", idref_map, "Toufic Khalil", "toufic khalil", {})
        assert result.person_id == 42
        assert result.rejection is None

    def test_surname_homonym_still_rejected(self):
        """Même patronyme, prénom franchement autre : reste rejeté (pas de fausse
        corroboration par graphie)."""
        idref_map = {"x": IdentifiedPerson(42, "chanal", "helene")}
        result = decide_match_by_identifier("x", idref_map, "Herve Chanal", "herve chanal", {})
        assert result.person_id is None
        assert result.rejection == (42, "helene chanal")


class TestDecidePersonMatch:
    """Cascade unifiée : ordre orcid > hal_person_id > idref > cross_source > name_form."""

    def _skip(self) -> NameFormDecision:
        return NameFormDecision(action="skip", reason="ambiguous_name_form")

    def test_orcid_wins_over_everything(self):
        decision = decide_person_match(
            orcid_match=99,
            hal_match=88,
            idref_match=17,
            cross_source_match=42,
            name_form_outcome=NameFormDecision(action="match", person_id=7),
        )
        assert decision == PersonMatchDecision(action="match", person_id=99, reason="orcid")

    def test_hal_wins_when_no_orcid(self):
        decision = decide_person_match(
            orcid_match=None,
            hal_match=88,
            idref_match=17,
            cross_source_match=42,
            name_form_outcome=NameFormDecision(action="match", person_id=7),
        )
        assert decision == PersonMatchDecision(action="match", person_id=88, reason="hal_person_id")

    def test_idref_wins_when_no_orcid_no_hal(self):
        decision = decide_person_match(
            orcid_match=None,
            hal_match=None,
            idref_match=17,
            cross_source_match=42,
            name_form_outcome=NameFormDecision(action="match", person_id=7),
        )
        assert decision == PersonMatchDecision(action="match", person_id=17, reason="idref")

    def test_name_match_wins_over_cross_source(self):
        # Le match par nom passe avant le cross-source (il maximise les ancres fermes).
        decision = decide_person_match(
            orcid_match=None,
            hal_match=None,
            idref_match=None,
            cross_source_match=42,
            name_form_outcome=NameFormDecision(action="match", person_id=7),
        )
        assert decision == PersonMatchDecision(action="match", person_id=7, reason="single_name")

    def test_cross_source_wins_over_compatible_initials(self):
        decision = decide_person_match(
            orcid_match=None,
            hal_match=None,
            idref_match=None,
            cross_source_match=42,
            name_form_outcome=NameFormDecision(
                action="match", person_id=7, reason="compatible_name"
            ),
        )
        assert decision == PersonMatchDecision(action="match", person_id=42, reason="cross_source")

    def test_compatible_initials_match_without_cross_source(self):
        decision = decide_person_match(
            orcid_match=None,
            hal_match=None,
            idref_match=None,
            cross_source_match=None,
            name_form_outcome=NameFormDecision(
                action="match", person_id=7, reason="compatible_name"
            ),
        )
        assert decision == PersonMatchDecision(
            action="match", person_id=7, reason="compatible_name"
        )

    def test_cross_source_wins_over_name_creation(self):
        # Le cross-source passe avant la création : une signature à créer préfère rejoindre
        # une ancre de même publication × position.
        decision = decide_person_match(
            orcid_match=None,
            hal_match=None,
            idref_match=None,
            cross_source_match=42,
            name_form_outcome=NameFormDecision(action="create"),
        )
        assert decision == PersonMatchDecision(action="match", person_id=42, reason="cross_source")

    def test_name_form_match_when_no_other_signal(self):
        decision = decide_person_match(
            orcid_match=None,
            hal_match=None,
            idref_match=None,
            cross_source_match=None,
            name_form_outcome=NameFormDecision(action="match", person_id=7),
        )
        assert decision == PersonMatchDecision(action="match", person_id=7, reason="single_name")

    def test_name_form_create_when_no_match(self):
        decision = decide_person_match(
            orcid_match=None,
            hal_match=None,
            idref_match=None,
            cross_source_match=None,
            name_form_outcome=NameFormDecision(action="create"),
        )
        assert decision == PersonMatchDecision(action="create", reason="new")

    def test_name_form_skip_ambiguous_propagates(self):
        decision = decide_person_match(
            orcid_match=None,
            hal_match=None,
            idref_match=None,
            cross_source_match=None,
            name_form_outcome=self._skip(),
        )
        assert decision == PersonMatchDecision(action="skip", reason="ambiguous_name_form")

    def test_name_form_skip_creation_not_allowed_propagates(self):
        """Rôle non-auteur d'une thèse : pas de création, pas de match."""
        decision = decide_person_match(
            orcid_match=None,
            hal_match=None,
            idref_match=None,
            cross_source_match=None,
            name_form_outcome=NameFormDecision(action="skip", reason="creation_not_allowed"),
        )
        assert decision == PersonMatchDecision(action="skip", reason="creation_not_allowed")

    def test_identifier_match_short_circuits_name_form_skip(self):
        """Un identifier match prend le pas sur un skip name_form
        (ambiguïté ou create interdit) — l'identifier est plus fiable."""
        decision = decide_person_match(
            orcid_match=None,
            hal_match=None,
            idref_match=17,
            cross_source_match=None,
            name_form_outcome=NameFormDecision(action="skip", reason="creation_not_allowed"),
        )
        assert decision == PersonMatchDecision(action="match", person_id=17, reason="idref")

    def test_cross_source_does_not_override_identifier(self):
        """Cross-source recule derrière les identifiants : un idref match gagne
        même si un cross-source est présent (inverse de l'ordre historique)."""
        decision = decide_person_match(
            orcid_match=None,
            hal_match=None,
            idref_match=17,
            cross_source_match=42,
            name_form_outcome=self._skip(),
        )
        assert decision == PersonMatchDecision(action="match", person_id=17, reason="idref")

    def test_rejected_orcid_match_falls_through_to_next_signal(self):
        """Un match ORCID vers une personne rejetée pour la publi est annulé ;
        la cascade retombe sur le hal_person_id."""
        decision = decide_person_match(
            orcid_match=99,
            hal_match=88,
            idref_match=17,
            cross_source_match=42,
            name_form_outcome=NameFormDecision(action="match", person_id=7),
            rejected_person_ids=frozenset({99}),
        )
        assert decision == PersonMatchDecision(action="match", person_id=88, reason="hal_person_id")

    def test_all_id_matches_rejected_falls_through_to_name_form(self):
        """Tous les matchs d'identifiant/cross-source rejetés → on retombe
        sur le name form (qui, lui, doit déjà être gardé en amont)."""
        decision = decide_person_match(
            orcid_match=99,
            hal_match=88,
            idref_match=17,
            cross_source_match=42,
            name_form_outcome=NameFormDecision(action="match", person_id=7),
            rejected_person_ids=frozenset({99, 88, 17, 42}),
        )
        assert decision == PersonMatchDecision(action="match", person_id=7, reason="single_name")

    def test_rejected_cross_source_match_skips_to_name_form_outcome(self):
        """Seul signal = cross-source, mais rejeté → on suit l'issue name form
        (ici skip ambigu)."""
        decision = decide_person_match(
            orcid_match=None,
            hal_match=None,
            idref_match=None,
            cross_source_match=42,
            name_form_outcome=self._skip(),
            rejected_person_ids=frozenset({42}),
        )
        assert decision == PersonMatchDecision(action="skip", reason="ambiguous_name_form")
