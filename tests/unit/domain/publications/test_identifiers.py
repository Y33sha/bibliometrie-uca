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
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("10.1234/test", "10.1234/test"),  # DOI nu
            ("https://doi.org/10.1234/test", "10.1234/test"),  # strip https
            ("http://doi.org/10.1234/test", "10.1234/test"),  # strip http
            ("https://dx.doi.org/10.1234/test", "10.1234/test"),  # strip dx.doi.org
            ("  10.1234/test  ", "10.1234/test"),  # strip whitespace
            ("10.6084/m9.figshare.31023197.v1", "10.6084/m9.figshare.31023197"),  # suffixe .vN
            ("10.36227/techrxiv.19754971.v2", "10.36227/techrxiv.19754971"),  # suffixe .v2
            ("10.1234/test/pdf", "10.1234/test"),  # suffixe /pdf
            ("https://doi.org/10.1234/test/PDF", "10.1234/test"),  # /PDF + strip url
            # Lowercase : CrossRef traite le DOI en case-insensitive ; lowercase
            # évite les faux doublons cross-sources.
            ("10.1038/Nature", "10.1038/nature"),
            ("10.1038/NATURE", "10.1038/nature"),
            ("https://doi.org/10.1038/NATURE", "10.1038/nature"),
        ],
    )
    def test_normalizes(self, raw, expected):
        assert DOI(raw).value == expected

    def test_str_returns_value(self):
        assert str(DOI("10.1234/test")) == "10.1234/test"

    def test_does_not_strip_v_not_followed_by_digit(self):
        """Un .v suivi de non-chiffre ne doit pas être strippé."""
        assert DOI("10.1234/journal.v12.issue3").value == "10.1234/journal.v12.issue3"

    @pytest.mark.parametrize(
        "raw",
        [
            "",  # vide
            "   ",  # whitespace seul
            "https://doi.org/",  # préfixe URL sans DOI
        ],
    )
    def test_raises_on_invalid(self, raw):
        with pytest.raises(ValidationError):
            DOI(raw)


class TestDOITryParse:
    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_returns_none_on_blank(self, raw):
        assert DOI.try_parse(raw) is None

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
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("hal-04123456", "hal-04123456"),  # portail HAL
            ("tel-02345678", "tel-02345678"),  # autres portails
            ("halshs-01234567", "halshs-01234567"),
            ("inserm-09876543", "inserm-09876543"),
            ("pasteur-11111111", "pasteur-11111111"),
            ("cea-22222222", "cea-22222222"),
            ("ineris-33333333", "ineris-33333333"),
            ("hal-04123456v2", "hal-04123456"),  # strip suffixe version
            ("HAL-04123456", "hal-04123456"),  # lowercase
            ("https://hal.science/hal-04123456", "hal-04123456"),  # strip URL
            ("https://hal.science/hal-04123456v2", "hal-04123456"),  # URL + version
            ("https://tel.archives-ouvertes.fr/tel-02345678", "tel-02345678"),  # URL autre portail
        ],
    )
    def test_normalizes(self, raw, expected):
        assert HALId(raw).value == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",  # vide
            "other-12345",  # préfixe inconnu
            "hal-",  # aucun chiffre
        ],
    )
    def test_raises_on_invalid(self, raw):
        with pytest.raises(ValidationError):
            HALId(raw)


class TestHALIdTryParse:
    def test_none(self):
        assert HALId.try_parse(None) is None

    def test_invalid(self):
        assert HALId.try_parse("garbage") is None

    def test_valid(self):
        assert HALId.try_parse("https://hal.science/hal-04123456v1").value == "hal-04123456"


# ── NNT ────────────────────────────────────────────────────────────


class TestNNT:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2021clfa0030", "2021CLFA0030"),  # uppercase
            ("  2021CLFA0030  ", "2021CLFA0030"),  # strip whitespace
        ],
    )
    def test_normalizes(self, raw, expected):
        assert NNT(raw).value == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",  # vide
            "   ",  # whitespace seul
            "2021-CLFA-0030",  # non alphanumérique
        ],
    )
    def test_raises_on_invalid(self, raw):
        with pytest.raises(ValidationError):
            NNT(raw)

    def test_try_parse_none(self):
        assert NNT.try_parse(None) is None

    def test_try_parse_invalid(self):
        assert NNT.try_parse("") is None
