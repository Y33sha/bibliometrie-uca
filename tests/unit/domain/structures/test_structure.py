"""Tests des value objects des structures : `RorId`, `HalCollection`."""

import pytest

from domain.errors import ValidationError
from domain.structures.identifiers import HalCollection, RorId


class TestRorId:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("02feahw73", "02feahw73"),  # forme courte
            ("https://ror.org/02feahw73", "02feahw73"),  # strip https
            ("http://ror.org/02feahw73", "02feahw73"),  # strip http
            ("ror.org/02feahw73", "02feahw73"),  # strip préfixe nu
            ("02FEAHW73", "02feahw73"),  # lowercase
        ],
    )
    def test_normalizes(self, raw, expected):
        assert RorId(raw).value == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "02feai073",  # 'i' interdit (alphabet ROR exclut i/l/o/u)
            "02feal073",  # 'l' interdit
            "02feahw7",  # 8 chars
            "02feahw733",  # 10 chars
            "12feahw73",  # mauvais préfixe (tous les ROR commencent par '0')
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
            ("  limos  ", "LIMOS"),  # case + whitespace
        ],
    )
    def test_normalizes(self, raw, expected):
        assert HalCollection(raw).value == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",  # vide
            "   ",  # whitespace seul
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
