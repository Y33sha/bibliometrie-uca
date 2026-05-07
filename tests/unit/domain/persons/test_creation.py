"""Tests des règles de politique de création de personnes."""

from domain.persons.creation import allow_person_creation


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
