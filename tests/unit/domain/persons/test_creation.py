"""Tests des règles de politique de création de personnes."""

from domain.persons.creation import allow_person_creation, should_create_source_person


class TestShouldCreateSourcePerson:
    def test_hal_with_positive_id(self):
        assert should_create_source_person(source="hal", strong_id_value=12345) is True

    def test_hal_with_zero_rejected(self):
        """hal_person_id=0 est une sentinelle interne 'auteur non identifié'."""
        assert should_create_source_person(source="hal", strong_id_value=0) is False

    def test_hal_with_negative_rejected(self):
        assert should_create_source_person(source="hal", strong_id_value=-1) is False

    def test_hal_with_none_rejected(self):
        assert should_create_source_person(source="hal", strong_id_value=None) is False

    def test_hal_with_string_rejected(self):
        """Type-strict côté HAL : un string n'est pas un id HAL valide."""
        assert should_create_source_person(source="hal", strong_id_value="12345") is False

    def test_scanr_with_idref(self):
        assert should_create_source_person(source="scanr", strong_id_value="252404955") is True

    def test_scanr_without_idref(self):
        assert should_create_source_person(source="scanr", strong_id_value=None) is False
        assert should_create_source_person(source="scanr", strong_id_value="") is False

    def test_theses_with_ppn(self):
        assert should_create_source_person(source="theses", strong_id_value="252404955") is True

    def test_theses_without_ppn(self):
        assert should_create_source_person(source="theses", strong_id_value=None) is False
        assert should_create_source_person(source="theses", strong_id_value="") is False


class TestAllowPersonCreation:
    def test_theses_author_role_allows_creation(self):
        assert allow_person_creation("theses", ["author"]) is True

    def test_theses_author_among_other_roles_allows_creation(self):
        """Une personne peut cumuler 'author' + 'thesis_director' pour des
        thèses différentes — la mention 'author' suffit ici."""
        assert allow_person_creation("theses", ["author", "thesis_director"]) is True

    def test_theses_thesis_director_alone_blocks_creation(self):
        assert allow_person_creation("theses", ["thesis_director"]) is False

    def test_theses_jury_blocks_creation(self):
        assert allow_person_creation("theses", ["jury_member"]) is False
        assert allow_person_creation("theses", ["jury_president"]) is False
        assert allow_person_creation("theses", ["rapporteur"]) is False

    def test_theses_no_roles_blocks_creation(self):
        """Pas de rôle = pas d'auteur identifié = pas de création."""
        assert allow_person_creation("theses", []) is False

    def test_other_sources_always_allow_creation(self):
        """Les sources sans nomenclature de rôle d'encadrement (HAL,
        OpenAlex, WoS, ScanR, Crossref) autorisent toujours la création."""
        for source in ("hal", "openalex", "wos", "scanr", "crossref"):
            assert allow_person_creation(source, []) is True
            assert allow_person_creation(source, ["author"]) is True
            # Même un rôle bizarre ne bloque pas (la règle est theses-spécifique)
            assert allow_person_creation(source, ["editor"]) is True
