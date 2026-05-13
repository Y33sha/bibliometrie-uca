"""Tests des value objects et helpers de domain/publications/identifiers.py
(DOI, HALId, NNT, clean_doi, normalize_nnt, extract_hal_id_from_url)."""

from dataclasses import FrozenInstanceError

import pytest

from domain.errors import ValidationError
from domain.publications.identifiers import (
    DOI,
    NNT,
    HALId,
)

# ── DOI ────────────────────────────────────────────────────────────


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

    def test_lowercases(self):
        """Le DOI complet est normalisé en minuscules (le standard CrossRef
        traite le DOI en case-insensitive ; lowercase évite les faux doublons
        cross-sources)."""
        assert DOI("10.1038/Nature").value == "10.1038/nature"
        assert DOI("10.1038/NATURE").value == "10.1038/nature"
        assert DOI("https://doi.org/10.1038/NATURE").value == "10.1038/nature"


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
        assert d.value == "10.1234/test"


class TestDOIImmutable:
    def test_is_frozen(self):
        d = DOI("10.1234/test")
        with pytest.raises(FrozenInstanceError):
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


# ── HALId ──────────────────────────────────────────────────────────


class TestHALIdConstruction:
    def test_accepts_plain_hal_id(self):
        assert HALId("hal-04123456").value == "hal-04123456"

    def test_accepts_other_portals(self):
        assert HALId("tel-02345678").value == "tel-02345678"
        assert HALId("halshs-01234567").value == "halshs-01234567"
        assert HALId("inserm-09876543").value == "inserm-09876543"
        assert HALId("pasteur-11111111").value == "pasteur-11111111"
        assert HALId("cea-22222222").value == "cea-22222222"
        assert HALId("ineris-33333333").value == "ineris-33333333"

    def test_strips_version_suffix(self):
        assert HALId("hal-04123456v2").value == "hal-04123456"

    def test_lowercases(self):
        assert HALId("HAL-04123456").value == "hal-04123456"

    def test_accepts_url(self):
        assert HALId("https://hal.science/hal-04123456").value == "hal-04123456"
        assert HALId("https://hal.science/hal-04123456v2").value == "hal-04123456"
        assert HALId("https://tel.archives-ouvertes.fr/tel-02345678").value == "tel-02345678"


class TestHALIdInvalid:
    def test_raises_on_empty(self):
        with pytest.raises(ValidationError):
            HALId("")

    def test_raises_on_unknown_prefix(self):
        with pytest.raises(ValidationError):
            HALId("other-12345")

    def test_raises_on_no_digits(self):
        with pytest.raises(ValidationError):
            HALId("hal-")


class TestHALIdTryParse:
    def test_none(self):
        assert HALId.try_parse(None) is None

    def test_invalid(self):
        assert HALId.try_parse("garbage") is None

    def test_valid(self):
        assert HALId.try_parse("https://hal.science/hal-04123456v1").value == "hal-04123456"


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
