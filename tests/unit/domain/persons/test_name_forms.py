"""Tests unitaires du VO `PersonNameForm`."""

import dataclasses

import pytest

from domain.errors import ValidationError
from domain.persons.name_forms import PersonNameForm


class TestPersonNameFormConstruction:
    def test_valid_string(self) -> None:
        form = PersonNameForm("jean dupont")
        assert form.value == "jean dupont"
        assert str(form) == "jean dupont"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValidationError):
            PersonNameForm("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValidationError):
            PersonNameForm("   ")


class TestPersonNameFormSemantics:
    def test_equality_by_value(self) -> None:
        assert PersonNameForm("jean dupont") == PersonNameForm("jean dupont")
        assert PersonNameForm("jean dupont") != PersonNameForm("jean martin")

    def test_hashable(self) -> None:
        forms = {PersonNameForm("jean dupont"), PersonNameForm("jean dupont")}
        assert len(forms) == 1

    def test_frozen(self) -> None:
        form = PersonNameForm("jean dupont")
        with pytest.raises(dataclasses.FrozenInstanceError):
            form.value = "autre"  # type: ignore[misc]
