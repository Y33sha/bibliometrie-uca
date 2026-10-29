"""Création d'une personne selon les rôles de la contribution."""

from domain.persons.creation import allow_person_creation


class TestAllowPersonCreation:
    def test_author_role_allows_creation(self):
        assert allow_person_creation(["author"]) is True

    def test_author_among_jury_roles_allows_creation(self):
        """Le rôle `author` suffit, même cumulé avec un rôle de jury."""
        assert allow_person_creation(["author", "thesis_director"]) is True

    def test_jury_roles_alone_block_creation(self):
        for roles in (
            ["thesis_director"],
            ["rapporteur"],
            ["jury_member"],
            ["jury_president"],
            ["jury_president", "rapporteur"],
        ):
            assert allow_person_creation(roles) is False

    def test_other_roles_allow_creation(self):
        for roles in (["editor"], ["contributor"], ["translator"], ["other"]):
            assert allow_person_creation(roles) is True

    def test_no_roles_allows_creation(self):
        assert allow_person_creation([]) is True
