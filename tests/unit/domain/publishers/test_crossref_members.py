"""Contradiction entre les membres Crossref de deux éditeurs."""

from domain.publishers.members import crossref_member_conflict


class TestCrossrefMemberConflict:
    def test_no_conflict_when_one_side_has_no_member(self):
        assert crossref_member_conflict([297], []) is None
        assert crossref_member_conflict([], [297]) is None
        assert crossref_member_conflict([], []) is None

    def test_no_conflict_when_a_member_is_shared(self):
        assert crossref_member_conflict([93, 297], [297]) is None

    def test_conflict_when_members_are_disjoint(self):
        conflict = crossref_member_conflict([93, 297], [793])
        assert conflict is not None
        assert "93, 297" in conflict
        assert "793" in conflict
