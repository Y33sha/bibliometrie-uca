"""Tests des value objects d'identifiants dans domain/identifiers.py."""

import pytest

from domain.errors import ValidationError
from domain.identifiers import DOI, NNT, ORCID, IdRef


class TestDOIConstruction:
    def test_accepts_plain_doi(self):
        d = DOI("10.1234/test")
        assert d.value == "10.1234/test"
        assert str(d) == "10.1234/test"

    def test_strips_https_prefix(self):
        assert DOI("https://doi.org/10.1234/test").value == "10.1234/test"

    def test_strips_http_prefix(self):
        assert DOI("http://doi.org/10.1234/test").value == "10.1234/test"

    def test_strips_dx_prefix(self):
        assert DOI("https://dx.doi.org/10.1234/test").value == "10.1234/test"

    def test_strips_whitespace(self):
        assert DOI("  10.1234/test  ").value == "10.1234/test"

    def test_normalizes_version_suffix(self):
        assert DOI("10.6084/m9.figshare.31023197.v1").value == "10.6084/m9.figshare.31023197"
        assert DOI("10.36227/techrxiv.19754971.v2").value == "10.36227/techrxiv.19754971"

    def test_does_not_strip_v_not_followed_by_digit(self):
        """Un .v suivi de non-chiffre ne doit pas être strippé."""
        assert DOI("10.1234/journal.v12.issue3").value == "10.1234/journal.v12.issue3"


class TestDOIInvalid:
    def test_raises_on_empty(self):
        with pytest.raises(ValidationError):
            DOI("")

    def test_raises_on_whitespace_only(self):
        with pytest.raises(ValidationError):
            DOI("   ")

    def test_raises_on_url_prefix_only(self):
        with pytest.raises(ValidationError):
            DOI("https://doi.org/")


class TestDOITryParse:
    def test_returns_none_on_none(self):
        assert DOI.try_parse(None) is None

    def test_returns_none_on_empty(self):
        assert DOI.try_parse("") is None

    def test_returns_none_on_whitespace(self):
        assert DOI.try_parse("   ") is None

    def test_returns_doi_on_valid(self):
        d = DOI.try_parse("10.1234/test")
        assert d is not None
        assert d.value == "10.1234/test"

    def test_normalizes_on_parse(self):
        d = DOI.try_parse("https://doi.org/10.1234/TEST.v3")
        assert d.value == "10.1234/TEST"


class TestDOIImmutable:
    def test_is_frozen(self):
        d = DOI("10.1234/test")
        with pytest.raises(Exception):  # FrozenInstanceError ou AttributeError
            d.value = "other"

    def test_is_hashable(self):
        """Deux DOI égaux doivent avoir le même hash (utilisable dans un set)."""
        a = DOI("10.1234/test")
        b = DOI("https://doi.org/10.1234/test")
        assert a == b
        assert hash(a) == hash(b)
        assert {a, b} == {a}

    def test_equality_by_normalized_value(self):
        """Deux DOI avec le même canon sont égaux même si écrits différemment."""
        assert DOI("10.1234/test") == DOI("  10.1234/test.v2  ")


# ── ORCID ──────────────────────────────────────────────────────────


class TestORCIDConstruction:
    def test_accepts_canonical_form(self):
        o = ORCID("0000-0001-2345-6789")
        assert o.value == "0000-0001-2345-6789"

    def test_accepts_with_checksum_X(self):
        o = ORCID("0000-0001-2345-678X")
        assert o.value == "0000-0001-2345-678X"

    def test_lowercases_x_to_uppercase(self):
        assert ORCID("0000-0001-2345-678x").value == "0000-0001-2345-678X"

    def test_strips_https_prefix(self):
        assert ORCID("https://orcid.org/0000-0001-2345-6789").value == "0000-0001-2345-6789"

    def test_strips_http_prefix(self):
        assert ORCID("http://orcid.org/0000-0001-2345-6789").value == "0000-0001-2345-6789"

    def test_strips_bare_orcid_org_prefix(self):
        assert ORCID("orcid.org/0000-0001-2345-6789").value == "0000-0001-2345-6789"

    def test_adds_hyphens_if_missing(self):
        assert ORCID("0000000123456789").value == "0000-0001-2345-6789"


class TestORCIDInvalid:
    def test_raises_on_empty(self):
        with pytest.raises(ValidationError):
            ORCID("")

    def test_raises_on_too_short(self):
        with pytest.raises(ValidationError):
            ORCID("0000-0001-2345")

    def test_raises_on_non_numeric_body(self):
        with pytest.raises(ValidationError):
            ORCID("0000-000A-2345-6789")

    def test_raises_on_wrong_shape(self):
        with pytest.raises(ValidationError):
            ORCID("garbage")


class TestORCIDTryParse:
    def test_none(self):
        assert ORCID.try_parse(None) is None

    def test_invalid(self):
        assert ORCID.try_parse("not an orcid") is None

    def test_valid(self):
        assert ORCID.try_parse("0000-0001-2345-6789") is not None


# ── IdRef ──────────────────────────────────────────────────────────


class TestIdRefConstruction:
    def test_accepts_canonical_ppn(self):
        assert IdRef("252404955").value == "252404955"

    def test_accepts_ppn_with_X(self):
        assert IdRef("05547854X").value == "05547854X"

    def test_lowercases_x_to_uppercase(self):
        assert IdRef("05547854x").value == "05547854X"

    def test_strips_idref_url(self):
        assert IdRef("https://www.idref.fr/252404955/id").value == "252404955"
        assert IdRef("idref.fr/252404955").value == "252404955"


class TestIdRefInvalid:
    def test_raises_on_empty(self):
        with pytest.raises(ValidationError):
            IdRef("")

    def test_raises_on_too_short(self):
        with pytest.raises(ValidationError):
            IdRef("12345678")  # 8 chiffres, il manque la clé

    def test_raises_on_too_long(self):
        with pytest.raises(ValidationError):
            IdRef("1234567890")

    def test_raises_on_letters_in_body(self):
        with pytest.raises(ValidationError):
            IdRef("12A456789")


# ── NNT ────────────────────────────────────────────────────────────


class TestNNT:
    def test_uppercases(self):
        assert NNT("2021clfa0030").value == "2021CLFA0030"

    def test_strips_whitespace(self):
        assert NNT("  2021CLFA0030  ").value == "2021CLFA0030"

    def test_raises_on_empty(self):
        with pytest.raises(ValidationError):
            NNT("")

    def test_raises_on_whitespace(self):
        with pytest.raises(ValidationError):
            NNT("   ")

    def test_raises_on_non_alnum(self):
        with pytest.raises(ValidationError):
            NNT("2021-CLFA-0030")

    def test_try_parse_none(self):
        assert NNT.try_parse(None) is None

    def test_try_parse_invalid(self):
        assert NNT.try_parse("") is None
