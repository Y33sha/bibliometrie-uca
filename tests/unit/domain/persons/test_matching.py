"""Tests des règles pures de matching d'authorships à des personnes."""

from domain.persons.matching import (
    NameFormDecision,
    PersonMatchDecision,
    decide_cross_source_match,
    decide_match_by_identifier,
    decide_name_form_outcome,
    decide_person_match,
    form_matches_person,
)


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

    def test_megapaper_short_circuits(self):
        """Au-delà du seuil méga-paper, on ne tente pas le cross-source
        (positions divergent trop entre sources sur les consortiums)."""
        candidates = [(42, "dupont", "jean", "hal")]
        assert (
            decide_cross_source_match(
                authorship_source="openalex",
                last_norm="dupont",
                first_norm="jean",
                candidates=candidates,
                total_author_count=120,
            )
            is None
        )

    def test_under_megapaper_threshold_passes_through(self):
        """En deçà du seuil, le match cross-source fonctionne normalement."""
        candidates = [(42, "dupont", "jean", "hal")]
        assert (
            decide_cross_source_match(
                authorship_source="openalex",
                last_norm="dupont",
                first_norm="jean",
                candidates=candidates,
                total_author_count=10,
            )
            == 42
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


class TestDecideMatchByIdentifier:
    def test_compatible_name_returns_person_id(self):
        idref_map = {"252404955": (42, "dupont", "jean")}
        result = decide_match_by_identifier(
            "252404955", idref_map, "Jean Dupont", "jean dupont", {}
        )
        assert result.person_id == 42
        assert result.rejection is None

    def test_incompatible_name_rejected(self):
        """Sans verdict, nom incompatible → match refusé (test de tokens), rejet journalisé."""
        idref_map = {"252404955": (42, "dupont", "jean")}
        result = decide_match_by_identifier(
            "252404955", idref_map, "Paul Martin", "paul martin", {}
        )
        assert result.person_id is None
        assert result.rejection == (42, "jean dupont")

    def test_confirmed_name_form_matches_without_token_test(self):
        """Forme confirmée pour la personne → match même si les tokens divergeraient
        (changement de nom : « Van Lander » confirmée pour « Maneval »)."""
        idref_map = {"x": (42, "maneval", "axelle")}
        status = {("van lander axelle", 42): "confirmed"}
        result = decide_match_by_identifier(
            "x", idref_map, "Van Lander Axelle", "van lander axelle", status
        )
        assert result.person_id == 42
        assert result.rejection is None

    def test_rejected_name_form_refused_even_if_compatible(self):
        """Forme rejetée pour la personne → refus même si les tokens seraient compatibles."""
        idref_map = {"x": (42, "dupont", "jean")}
        status = {("jean dupont", 42): "rejected"}
        result = decide_match_by_identifier("x", idref_map, "Jean Dupont", "jean dupont", status)
        assert result.person_id is None
        assert result.rejection == (42, "jean dupont")

    def test_value_absent_returns_empty(self):
        idref_map = {"252404955": (42, "dupont", "jean")}
        result = decide_match_by_identifier("999999999", idref_map, "X", "x", {})
        assert result.person_id is None
        assert result.rejection is None

    def test_falsy_value_returns_empty(self):
        """Pas de tentative de lookup si la valeur est vide/None."""
        m = {"foo": (1, "a", "b")}
        assert decide_match_by_identifier(None, m, "X", "x", {}).person_id is None
        assert decide_match_by_identifier("", m, "X", "x", {}).person_id is None

    def test_empty_map(self):
        assert decide_match_by_identifier("anything", {}, "X", "x", {}).person_id is None

    def test_surname_only_signature_not_rejected(self):
        """Signature trop pauvre (nom seul) : compatible (sous-ensemble de tokens),
        donc pas de refus — on s'abstient plutôt que de rejeter."""
        idref_map = {"x": (42, "dupont", "jean")}
        result = decide_match_by_identifier("x", idref_map, "Dupont", "dupont", {})
        assert result.person_id == 42
        assert result.rejection is None

    def test_works_for_orcid_too(self):
        """La fonction est générique : même contrat pour IdRef et ORCID."""
        orcid_map = {"0000-0001-2345-6789": (7, "curie", "marie")}
        result = decide_match_by_identifier(
            "0000-0001-2345-6789", orcid_map, "Marie Curie", "marie curie", {}
        )
        assert result.person_id == 7

    def test_graphie_variant_corroborates(self):
        """Variante de graphie du propriétaire (concaténation) : corrobore et se
        rattache, au lieu d'être rejetée puis dédoublée au canal nominal."""
        idref_map = {"x": (42, "gannoun", "abdel mouhcine")}
        result = decide_match_by_identifier(
            "x", idref_map, "Abdelmouhcine Gannoun", "abdelmouhcine gannoun", {}
        )
        assert result.person_id == 42
        assert result.rejection is None

    def test_surname_homonym_still_rejected(self):
        """Même patronyme, prénom franchement autre : reste rejeté (pas de fausse
        corroboration par graphie)."""
        idref_map = {"x": (42, "chanal", "helene")}
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

    def test_cross_source_wins_when_no_identifier(self):
        decision = decide_person_match(
            orcid_match=None,
            hal_match=None,
            idref_match=None,
            cross_source_match=42,
            name_form_outcome=NameFormDecision(action="match", person_id=7),
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
