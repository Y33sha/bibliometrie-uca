"""Tests de l'entité fille ``Authorship`` (scaffolding Phase 1)."""

from domain.publications.authorship import Authorship


class TestAuthorshipConstruction:
    def test_accepts_minimal_args(self):
        a = Authorship(id=None, publication_id=42)
        assert a.id is None
        assert a.publication_id == 42
        assert a.person_id is None
        assert a.in_perimeter is False
        assert a.source_manual is False
        assert a.excluded is False
        assert a.roles == ()
        assert a.structure_ids == ()

    def test_accepts_full_args(self):
        a = Authorship(
            id=1,
            publication_id=42,
            person_id=7,
            author_position=2,
            in_perimeter=True,
            source_manual=True,
            excluded=False,
            is_corresponding=True,
            roles=("author", "thesis_director"),
            structure_ids=(10, 20),
            notes="manual override",
        )
        assert a.id == 1
        assert a.author_position == 2
        assert a.in_perimeter is True
        assert a.is_corresponding is True
        assert a.roles == ("author", "thesis_director")
        assert a.structure_ids == (10, 20)
        assert a.notes == "manual override"
