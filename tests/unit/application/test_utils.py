"""Normalisation de texte, nettoyage de DOI, découpage et comparaison de noms d'auteurs."""

import pytest

from domain.normalize import normalize_text
from domain.persons.name_matching import (
    names_compatible,
    parse_raw_author_name,
)
from domain.publications.identifiers import clean_doi


class TestNormalizeName:
    def test_accents(self):
        assert normalize_text("José García") == "jose garcia"

    def test_punctuation(self):
        # L'apostrophe est remplacée par un espace
        assert normalize_text("O'Brien-Smith") == "o brien smith"

    def test_none(self):
        assert normalize_text(None) == ""

    def test_empty(self):
        assert normalize_text("") == ""

    def test_uppercase(self):
        assert normalize_text("DUPONT") == "dupont"

    def test_digits_kept(self):
        # normalize_text conserve les chiffres
        assert normalize_text("Jean2") == "jean2"

    def test_multiple_spaces(self):
        assert normalize_text("  Jean   Dupont  ") == "jean dupont"

    def test_unicode_hyphen(self):
        """Les tirets Unicode (U+2010, U+2013) séparent les mots comme le tiret ASCII : les trois graphies d'un nom composé donnent la même forme."""
        assert normalize_text("Abeywickrama\u2010Samarakoon") == "abeywickrama samarakoon"
        assert normalize_text("Abeywickrama\u2013Samarakoon") == "abeywickrama samarakoon"
        assert normalize_text("Abeywickrama-Samarakoon") == "abeywickrama samarakoon"

    def test_unicode_apostrophe(self):
        """L'apostrophe typographique sépare les mots comme l'apostrophe ASCII."""
        assert normalize_text("O\u2019Brien") == "o brien"
        assert normalize_text("O'Brien") == "o brien"


class TestCleanDoi:
    def test_strip_https(self):
        assert clean_doi("https://doi.org/10.1234/test") == "10.1234/test"

    def test_strip_http(self):
        assert clean_doi("http://doi.org/10.1234/test") == "10.1234/test"

    def test_plain_doi(self):
        assert clean_doi("10.1234/test") == "10.1234/test"

    def test_none(self):
        assert clean_doi(None) is None

    def test_empty(self):
        assert clean_doi("") is None

    def test_whitespace(self):
        assert clean_doi("  10.1234/test  ") == "10.1234/test"

    def test_version_suffix_kept(self):
        assert clean_doi("10.6084/m9.figshare.31023197.v1") == "10.6084/m9.figshare.31023197.v1"

    def test_no_false_positive_on_v_in_doi(self):
        """Un `.v` suivi d'autre chose qu'un chiffre est conservé."""
        assert clean_doi("10.1234/journal.v12.issue3") == "10.1234/journal.v12.issue3"


class TestParseRawAuthorName:
    def test_comma_format(self):
        assert parse_raw_author_name("Dupont, Jean") == ("Dupont", "Jean")

    def test_only_the_first_comma_separates_last_from_first_name(self):
        assert parse_raw_author_name("Martin, Jean-Luc, Jr.") == ("Martin", "Jean-Luc, Jr.")

    def test_space_format(self):
        assert parse_raw_author_name("Jean Dupont") == ("Dupont", "Jean")

    def test_multiple_first_names(self):
        assert parse_raw_author_name("Jean Pierre Dupont") == ("Dupont", "Jean Pierre")

    @pytest.mark.parametrize(
        ("raw", "parsed"),
        [
            ("Alison da Silva", ("da Silva", "Alison")),
            ("Nada El Osta", ("El Osta", "Nada")),
            ("Jan van der Berg", ("van der Berg", "Jan")),
            ("Benjamin van Wyk de Vries", ("van Wyk de Vries", "Benjamin")),
            ("Jean d' Ormesson", ("d' Ormesson", "Jean")),
            ("Marie d'Aboville Lefort", ("d'Aboville Lefort", "Marie")),
            ("Guilherme D. da Fonseca", ("da Fonseca", "Guilherme D.")),
        ],
    )
    def test_family_name_opens_at_the_first_particle(self, raw, parsed):
        assert parse_raw_author_name(raw) == parsed

    @pytest.mark.parametrize(
        ("raw", "parsed"),
        [
            ("Del Buono L.", ("Del Buono", "L.")),
            ("Solovyanov O. V.", ("Solovyanov", "O. V.")),
            ("Bal M. -C.", ("Bal", "M. -C.")),
            ("Amziane S", ("Amziane", "S")),
        ],
    )
    def test_trailing_initials_form_the_first_name(self, raw, parsed):
        assert parse_raw_author_name(raw) == parsed

    def test_leading_initial_stays_first_name(self):
        assert parse_raw_author_name("J. Dupont") == ("Dupont", "J.")

    def test_initials_before_the_comma_are_the_first_name(self):
        assert parse_raw_author_name("C., Küll") == ("Küll", "C.")

    def test_single_name(self):
        assert parse_raw_author_name("Dupont") == ("Dupont", "")

    def test_none(self):
        assert parse_raw_author_name(None) == ("", "")

    def test_empty(self):
        assert parse_raw_author_name("") == ("", "")


class TestNamesCompatible:
    def test_identical(self):
        assert names_compatible("dupont", "jean", "dupont", "jean") is True

    def test_initial(self):
        assert names_compatible("dupont", "j", "dupont", "jean") is True

    def test_different_last(self):
        assert names_compatible("dupont", "jean", "martin", "jean") is False

    def test_different_first(self):
        assert names_compatible("dupont", "jean", "dupont", "pierre") is False

    def test_inverted(self):
        # Nom et prénom inversés : les tokens des deux champs sont comparés ensemble.
        assert names_compatible("jean", "dupont", "dupont", "jean") is True

    def test_composite_last_name_reordered(self):
        # Ordre des composants du nom de famille indifférent : « Combes-Motel » ↔ « Motel Combes ».
        assert names_compatible("combes motel", "pascale", "motel combes", "pascale") is True

    def test_first_name_prefix(self):
        # "jean" compatible avec "jean luc" (sous-ensemble de tokens).
        assert names_compatible("dupont", "jean", "dupont", "jean luc") is True

    def test_joined_initials(self):
        # « J-L Bailly » ↔ « Jean Luc Bailly » : initiales séparées tolérées.
        assert names_compatible("bailly", "j l", "bailly", "jean luc") is True

    def test_surname_only_is_compatible(self):
        # Contribution source réduite au nom de famille : ses tokens sont un sous-ensemble du nom complet, donc compatibles.
        assert names_compatible("dupont", "", "dupont", "jean") is True

    def test_digits_ignored(self):
        # Les chiffres (année de naissance du Sudoc) sont retirés avant la comparaison.
        assert names_compatible("chiari", "sophie 1977", "chiari lasserre", "sophie") is True
