"""Tests des identifiants de structure : `RorId` et `HalCollection`."""

import pytest

from domain.errors import ValidationError
from domain.structures.identifiers import HalCollection, RorId


class TestRorId:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("02feahw73", "02feahw73"),  # forme courte
            ("https://ror.org/02feahw73", "02feahw73"),  # schéma https retiré
            ("http://ror.org/02feahw73", "02feahw73"),  # schéma http retiré
            ("ror.org/02feahw73", "02feahw73"),  # domaine retiré
            ("02FEAHW73", "02feahw73"),  # minuscules
        ],
    )
    def test_normalizes(self, raw, expected):
        assert RorId(raw).value == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "02feai073",  # 'i' interdit (l'alphabet ROR exclut i, l, o, u)
            "02feal073",  # 'l' interdit
            "02feahw7",  # 8 caractères
            "02feahw733",  # 10 caractères
            "12feahw73",  # premier caractère autre que '0'
        ],
    )
    def test_raises_on_invalid(self, raw):
        with pytest.raises(ValidationError):
            RorId(raw)

    @pytest.mark.parametrize("raw", [None, "", "garbage"])
    def test_try_parse_returns_none_on_invalid(self, raw):
        assert RorId.try_parse(raw) is None

    def test_try_parse_valid(self):
        assert RorId.try_parse("02feahw73").value == "02feahw73"

    def test_str_returns_canonical(self):
        assert str(RorId("https://ror.org/02feahw73")) == "02feahw73"


class TestHalCollection:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("LIMOS", "LIMOS"),  # code simple
            ("INSTITUT_PASCAL", "INSTITUT_PASCAL"),  # underscore
            ("LPC-CLERMONT", "LPC-CLERMONT"),  # tiret
            ("  limos  ", "LIMOS"),  # casse et espaces
        ],
    )
    def test_normalizes(self, raw, expected):
        assert HalCollection(raw).value == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",  # vide
            "   ",  # espaces seuls
            "LAB X",  # espace interne
            "LABO.X",  # point
            "ÉCOLE",  # accent
        ],
    )
    def test_raises_on_invalid(self, raw):
        with pytest.raises(ValidationError):
            HalCollection(raw)

    @pytest.mark.parametrize("raw", [None, "", "LAB X"])
    def test_try_parse_returns_none_on_invalid(self, raw):
        assert HalCollection.try_parse(raw) is None

    def test_try_parse_valid(self):
        assert HalCollection.try_parse("LIMOS").value == "LIMOS"
