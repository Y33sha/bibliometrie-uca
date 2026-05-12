"""Tests unitaires du VO `Address`."""

import dataclasses

import pytest

from domain.addresses.address import Address
from domain.errors import ValidationError


class TestAddressConstruction:
    def test_valid_text(self) -> None:
        addr = Address(normalized_text="universite clermont auvergne, clermont-ferrand, france")
        assert addr.normalized_text == "universite clermont auvergne, clermont-ferrand, france"
        assert str(addr) == "universite clermont auvergne, clermont-ferrand, france"

    def test_empty_raises(self) -> None:
        with pytest.raises(ValidationError):
            Address(normalized_text="")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValidationError):
            Address(normalized_text="   ")


class TestAddressSemantics:
    def test_equality_by_value(self) -> None:
        a = Address(normalized_text="uca, clermont")
        b = Address(normalized_text="uca, clermont")
        c = Address(normalized_text="autre, paris")
        assert a == b
        assert a != c

    def test_hashable(self) -> None:
        addrs = {Address(normalized_text="uca"), Address(normalized_text="uca")}
        assert len(addrs) == 1

    def test_frozen(self) -> None:
        addr = Address(normalized_text="uca")
        with pytest.raises(dataclasses.FrozenInstanceError):
            addr.normalized_text = "autre"  # type: ignore[misc]
