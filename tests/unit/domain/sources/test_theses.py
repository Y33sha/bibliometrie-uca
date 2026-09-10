from domain.sources.theses import (
    aggregate_thesis_persons,
    derive_theses_doc_type,
)


class TestDeriveThesesDocType:
    def test_with_date_soutenance_returns_thesis(self):
        assert derive_theses_doc_type("2023-05-10") == "thesis"
        assert derive_theses_doc_type("01/06/2024") == "thesis"

    def test_without_date_soutenance_returns_ongoing_thesis(self):
        assert derive_theses_doc_type(None) == "ongoing_thesis"
        assert derive_theses_doc_type("") == "ongoing_thesis"


class TestAggregateThesisPersons:
    def test_single_author(self):
        these = {"auteurs": [{"nom": "Dupont", "prenom": "Jean", "ppn": "111111111"}]}
        result = aggregate_thesis_persons(these)
        assert len(result) == 1
        a = result[0]
        assert a.is_author is True
        assert a.author_position == 0
        assert a.roles == ["author"]
        assert a.raw_author_name == "Jean Dupont"
        assert a.person_identifiers == {"idref": "111111111"}

    def test_two_authors_get_consecutive_positions(self):
        these = {
            "auteurs": [
                {"nom": "A", "prenom": "Anne"},
                {"nom": "B", "prenom": "Bob"},
            ]
        }
        result = aggregate_thesis_persons(these)
        assert [a.author_position for a in result] == [0, 1]

    def test_director_has_no_position(self):
        these = {
            "auteurs": [{"nom": "A", "prenom": "Anne"}],
            "directeurs": [{"nom": "D", "prenom": "Diana", "ppn": "222"}],
        }
        result = aggregate_thesis_persons(these)
        director = next(a for a in result if "thesis_director" in a.roles)
        assert director.author_position is None
        assert director.is_author is False

    def test_dedup_by_ppn_across_fields(self):
        """Une personne (même PPN) qui apparaît rapporteur ET président : 1 entrée, 2 rôles."""
        person = {"nom": "X", "prenom": "Xavier", "ppn": "999"}
        these = {
            "rapporteurs": [person],
            "president": person,
        }
        result = aggregate_thesis_persons(these)
        assert len(result) == 1
        assert sorted(result[0].roles) == ["jury_president", "rapporteur"]

    def test_dedup_by_name_when_no_ppn(self):
        these = {
            "rapporteurs": [{"nom": "X", "prenom": "Xavier"}],
            "president": {"nom": "X", "prenom": "Xavier"},
        }
        result = aggregate_thesis_persons(these)
        assert len(result) == 1
        assert sorted(result[0].roles) == ["jury_president", "rapporteur"]

    def test_no_ppn_yields_none_identifiers(self):
        these = {"auteurs": [{"nom": "Dupont", "prenom": "Jean"}]}
        assert aggregate_thesis_persons(these)[0].person_identifiers is None

    def test_president_singular_field(self):
        these = {"president": {"nom": "P", "prenom": "Pierre"}}
        result = aggregate_thesis_persons(these)
        assert len(result) == 1
        assert result[0].roles == ["jury_president"]
        assert result[0].author_position is None

    def test_skips_persons_without_nom(self):
        these = {"auteurs": [{"nom": "", "prenom": "Jean"}, {"prenom": "Sansnom"}]}
        assert aggregate_thesis_persons(these) == []

    def test_a_person_without_nom_leaves_the_next_one(self):
        these = {"auteurs": [{"prenom": "Sansnom"}, {"nom": "Dupont", "prenom": "Jean"}]}
        assert [a.raw_author_name for a in aggregate_thesis_persons(these)] == ["Jean Dupont"]

    def test_dedup_by_ppn_despite_name_variants(self):
        these = {
            "rapporteurs": [{"nom": "Durand", "prenom": "Élise", "ppn": "999"}],
            "president": {"nom": "Durand-Martin", "prenom": "E.", "ppn": "999"},
        }
        assert len(aggregate_thesis_persons(these)) == 1

    def test_homonyms_with_distinct_ppn_stay_distinct(self):
        these = {
            "rapporteurs": [{"nom": "Martin", "prenom": "Paul", "ppn": "111"}],
            "president": {"nom": "Martin", "prenom": "Paul", "ppn": "222"},
        }
        assert len(aggregate_thesis_persons(these)) == 2

    def test_without_ppn_distinct_first_names_stay_distinct(self):
        these = {
            "rapporteurs": [{"nom": "Martin", "prenom": "Paul"}],
            "president": {"nom": "Martin", "prenom": "Anne"},
        }
        assert len(aggregate_thesis_persons(these)) == 2

    def test_author_without_prenom(self):
        these = {"auteurs": [{"nom": "Dupont"}]}
        assert aggregate_thesis_persons(these)[0].raw_author_name == "Dupont"

    def test_raw_person_is_passed_through(self):
        person = {"nom": "Dupont", "prenom": "Jean", "ppn": "111111111"}
        assert aggregate_thesis_persons({"auteurs": [person]})[0].person == person

    def test_three_authors_get_consecutive_positions(self):
        these = {"auteurs": [{"nom": "A"}, {"nom": "B"}, {"nom": "C"}]}
        assert [a.author_position for a in aggregate_thesis_persons(these)] == [0, 1, 2]

    def test_empty_input(self):
        assert aggregate_thesis_persons({}) == []
