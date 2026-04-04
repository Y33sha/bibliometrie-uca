"""Tests unitaires — fonctions pures, sans base de données."""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from utils.normalize import normalize_name, normalize_text
from utils.doi import clean_doi
from utils.names import (
    parse_raw_author_name, names_compatible, first_names_compatible,
    last_names_compatible,
)
from services.persons import compute_person_name_forms


# ── normalize_name ──

class TestNormalizeName:
    def test_accents(self):
        assert normalize_name("José García") == "jose garcia"

    def test_punctuation(self):
        # L'apostrophe est remplacée par un espace
        assert normalize_name("O'Brien-Smith") == "o brien smith"

    def test_none(self):
        assert normalize_name(None) == ""

    def test_empty(self):
        assert normalize_name("") == ""

    def test_uppercase(self):
        assert normalize_name("DUPONT") == "dupont"

    def test_digits_kept(self):
        # normalize_name conserve les chiffres (aligné sur normalize_name_form SQL)
        assert normalize_name("Jean2") == "jean2"

    def test_multiple_spaces(self):
        assert normalize_name("  Jean   Dupont  ") == "jean dupont"


# ── clean_doi ──

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


# ── parse_raw_author_name ──

class TestParseRawAuthorName:
    def test_comma_format(self):
        assert parse_raw_author_name("Dupont, Jean") == ("Dupont", "Jean")

    def test_space_format(self):
        # "Jean Dupont" → last=Dupont, first=Jean
        assert parse_raw_author_name("Jean Dupont") == ("Dupont", "Jean")

    def test_multiple_first_names(self):
        assert parse_raw_author_name("Jean Pierre Dupont") == ("Dupont", "Jean Pierre")

    def test_single_name(self):
        assert parse_raw_author_name("Dupont") == ("Dupont", "")

    def test_none(self):
        assert parse_raw_author_name(None) == ("", "")

    def test_empty(self):
        assert parse_raw_author_name("") == ("", "")


# ── names_compatible ──

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
        # Inversion nom/prénom
        assert names_compatible("jean", "dupont", "dupont", "jean") is True

    def test_composite_last_name(self):
        assert last_names_compatible("araujo da silva", "araujo da silva") is True

    def test_first_name_prefix(self):
        # "jean" compatible avec "jean luc"
        assert first_names_compatible("jean", "jean luc") is True

    def test_empty_first_name(self):
        assert first_names_compatible("", "jean") is False


# ── compute_person_name_forms ──

class TestComputePersonNameForms:
    def test_standard(self):
        forms = compute_person_name_forms("Dupont", "Jean")
        assert "jean dupont" in forms
        assert "dupont jean" in forms
        assert "j dupont" in forms
        assert "dupont j" in forms

    def test_compound_first_name(self):
        forms = compute_person_name_forms("Dupont", "Jean Michel")
        assert "jean michel dupont" in forms
        assert "j m dupont" in forms
        assert "jm dupont" in forms

    def test_no_first_name(self):
        forms = compute_person_name_forms("Dupont", "")
        assert "dupont" in forms
        assert len(forms) == 1

    def test_empty_last_name(self):
        forms = compute_person_name_forms("", "Jean")
        assert forms == set()
