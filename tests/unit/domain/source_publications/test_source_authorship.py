"""Tests de l'entité fille ``SourceAuthorship`` (scaffolding Phase 1)."""

from domain.source_publications.source_authorship import SourceAuthorship


class TestSourceAuthorshipConstruction:
    def test_accepts_minimal_args(self):
        sa = SourceAuthorship(id=None, source_publication_id=42, source="hal")
        assert sa.id is None
        assert sa.source_publication_id == 42
        assert sa.source == "hal"
        assert sa.person_id is None
        assert sa.authorship_id is None
        assert sa.roles == ("author",)
        assert sa.is_corresponding is False
        assert sa.in_perimeter is False

    def test_accepts_full_args(self):
        sa = SourceAuthorship(
            id=1,
            source_publication_id=42,
            source="hal",
            author_position=2,
            person_id=7,
            authorship_id=99,
            raw_author_name="Jean Dupont",
            author_name_normalized="dupont jean",
            in_perimeter=True,
            is_corresponding=True,
            roles=("author", "thesis_director"),
            structure_ids=(10, 20),
            source_structures=("UMR-1234",),
            countries=("FR",),
            person_identifiers={"orcid": "0000-0000-0000-0001"},
            source_data={"raw": True},
        )
        assert sa.person_id == 7
        assert sa.authorship_id == 99
        assert sa.author_name_normalized == "dupont jean"
        assert sa.is_corresponding is True
        assert sa.person_identifiers == {"orcid": "0000-0000-0000-0001"}
        assert sa.source_data == {"raw": True}
