from domain.sources.theses import (
    aggregate_thesis_persons,
    derive_theses_doc_type,
    thesis_authors_compatible,
)


class TestThesisAuthorsCompatible:
    """Variations d'ordre / particules acceptées, mauvais nom rejeté."""

    def test_exact_match(self):
        assert thesis_authors_compatible(("Dupont", "Jean"), ("dupont", "jean")) is True

    def test_no_primary_author_accepts(self):
        """Pas d'auteur connu en BDD → on accepte (titre+année font foi)."""
        assert thesis_authors_compatible(None, ("dupont", "jean")) is True

    def test_empty_primary_last_name_accepts(self):
        assert thesis_authors_compatible(("", ""), ("dupont", "jean")) is True

    def test_incompatible_names(self):
        assert thesis_authors_compatible(("Martin", "Paul"), ("dupont", "jean")) is False

    def test_token_fallback_particule(self):
        """Gère les particules (Ben, Le…) via set des tokens identiques."""
        assert thesis_authors_compatible(("Ben Ali", "Mohammed"), ("mohammed", "ben ali")) is True


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

    def test_empty_input(self):
        assert aggregate_thesis_persons({}) == []
