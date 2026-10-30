from domain.persons.contributor_name import ContributorName
from pipeline.ingestion.theses.payload import aggregate_thesis_persons, derive_theses_doc_type


class TestDeriveThesesDocType:
    def test_with_date_soutenance_returns_thesis(self):
        assert derive_theses_doc_type("2023-05-10") == "thesis"
        assert derive_theses_doc_type("01/06/2024") == "thesis"

    def test_without_date_soutenance_returns_ongoing_thesis(self):
        assert derive_theses_doc_type(None) == "ongoing_thesis"
        assert derive_theses_doc_type("") == "ongoing_thesis"


class TestAggregateThesisPersons:
    def test_single_author(self):
        thesis = {"auteurs": [{"nom": "Dupont", "prenom": "Jean", "ppn": "111111111"}]}
        result = aggregate_thesis_persons(thesis)
        assert len(result) == 1
        a = result[0]
        assert a.is_author is True
        assert a.author_position == 0
        assert a.roles == ["author"]
        assert a.name == ContributorName(last_name="Dupont", first_name="Jean")
        assert a.identifiers == {"idref": "111111111"}

    def test_two_authors_get_consecutive_positions(self):
        thesis = {
            "auteurs": [
                {"nom": "A", "prenom": "Anne"},
                {"nom": "B", "prenom": "Bob"},
            ]
        }
        result = aggregate_thesis_persons(thesis)
        assert [a.author_position for a in result] == [0, 1]

    def test_director_has_no_position(self):
        thesis = {
            "auteurs": [{"nom": "A", "prenom": "Anne"}],
            "directeurs": [{"nom": "D", "prenom": "Diana", "ppn": "222"}],
        }
        result = aggregate_thesis_persons(thesis)
        director = next(a for a in result if "thesis_director" in a.roles)
        assert director.author_position is None
        assert director.is_author is False

    def test_dedup_by_ppn_across_fields(self):
        """Une personne (même PPN) à la fois rapporteur et président donne une entrée à deux rôles."""
        person = {"nom": "X", "prenom": "Xavier", "ppn": "999"}
        thesis = {
            "rapporteurs": [person],
            "presidentJury": person,
        }
        result = aggregate_thesis_persons(thesis)
        assert len(result) == 1
        assert sorted(result[0].roles) == ["jury_president", "rapporteur"]

    def test_dedup_by_name_when_no_ppn(self):
        thesis = {
            "rapporteurs": [{"nom": "X", "prenom": "Xavier"}],
            "presidentJury": {"nom": "X", "prenom": "Xavier"},
        }
        result = aggregate_thesis_persons(thesis)
        assert len(result) == 1
        assert sorted(result[0].roles) == ["jury_president", "rapporteur"]

    def test_no_ppn_yields_none_identifiers(self):
        thesis = {"auteurs": [{"nom": "Dupont", "prenom": "Jean"}]}
        assert aggregate_thesis_persons(thesis)[0].identifiers is None

    def test_president_singular_field(self):
        thesis = {"presidentJury": {"nom": "P", "prenom": "Pierre"}}
        result = aggregate_thesis_persons(thesis)
        assert len(result) == 1
        assert result[0].roles == ["jury_president"]
        assert result[0].author_position is None

    def test_skips_persons_without_nom(self):
        thesis = {"auteurs": [{"nom": "", "prenom": "Jean"}, {"prenom": "Sansnom"}]}
        assert aggregate_thesis_persons(thesis) == []

    def test_a_person_without_nom_leaves_the_next_one(self):
        thesis = {"auteurs": [{"prenom": "Sansnom"}, {"nom": "Dupont", "prenom": "Jean"}]}
        assert [a.name.display() for a in aggregate_thesis_persons(thesis)] == ["Jean Dupont"]

    def test_dedup_by_ppn_despite_name_variants(self):
        thesis = {
            "rapporteurs": [{"nom": "Durand", "prenom": "Élise", "ppn": "999"}],
            "presidentJury": {"nom": "Durand-Martin", "prenom": "E.", "ppn": "999"},
        }
        assert len(aggregate_thesis_persons(thesis)) == 1

    def test_homonyms_with_distinct_ppn_stay_distinct(self):
        thesis = {
            "rapporteurs": [{"nom": "Martin", "prenom": "Paul", "ppn": "111"}],
            "presidentJury": {"nom": "Martin", "prenom": "Paul", "ppn": "222"},
        }
        assert len(aggregate_thesis_persons(thesis)) == 2

    def test_without_ppn_distinct_first_names_stay_distinct(self):
        thesis = {
            "rapporteurs": [{"nom": "Martin", "prenom": "Paul"}],
            "presidentJury": {"nom": "Martin", "prenom": "Anne"},
        }
        assert len(aggregate_thesis_persons(thesis)) == 2

    def test_author_without_prenom(self):
        thesis = {"auteurs": [{"nom": "Dupont"}]}
        assert aggregate_thesis_persons(thesis)[0].name == ContributorName(last_name="Dupont")

    def test_raw_person_is_passed_through(self):
        person = {"nom": "Dupont", "prenom": "Jean", "ppn": "111111111"}
        assert aggregate_thesis_persons({"auteurs": [person]})[0].person == person

    def test_three_authors_get_consecutive_positions(self):
        thesis = {"auteurs": [{"nom": "A"}, {"nom": "B"}, {"nom": "C"}]}
        assert [a.author_position for a in aggregate_thesis_persons(thesis)] == [0, 1, 2]

    def test_empty_input(self):
        assert aggregate_thesis_persons({}) == []
