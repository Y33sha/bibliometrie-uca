"""Tests unitaires du VO `StructureNameForm`."""

import dataclasses

import pytest

from domain.errors import ValidationError
from domain.structures.name_forms import StructureNameForm


class TestStructureNameFormConstruction:
    def test_minimal_valid(self) -> None:
        form = StructureNameForm(form_text="INRAE")
        assert form.form_text == "INRAE"
        assert form.is_word_boundary is False
        assert form.is_excluding is False
        assert form.requires_context_of == ()

    def test_with_all_options(self) -> None:
        form = StructureNameForm(
            form_text="LIMOS",
            is_word_boundary=True,
            is_excluding=False,
            requires_context_of=(12, 34),
        )
        assert form.form_text == "LIMOS"
        assert form.is_word_boundary is True
        assert form.requires_context_of == (12, 34)

    def test_empty_text_raises(self) -> None:
        with pytest.raises(ValidationError):
            StructureNameForm(form_text="")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValidationError):
            StructureNameForm(form_text="   ")


class TestStructureNameFormSemantics:
    def test_equality_by_value(self) -> None:
        a = StructureNameForm(form_text="INRAE", is_word_boundary=True)
        b = StructureNameForm(form_text="INRAE", is_word_boundary=True)
        c = StructureNameForm(form_text="INRAE", is_word_boundary=False)
        assert a == b
        assert a != c

    def test_hashable_with_context_tuple(self) -> None:
        forms = {
            StructureNameForm(form_text="X", requires_context_of=(1, 2)),
            StructureNameForm(form_text="X", requires_context_of=(1, 2)),
        }
        assert len(forms) == 1

    def test_frozen(self) -> None:
        form = StructureNameForm(form_text="INRAE")
        with pytest.raises(dataclasses.FrozenInstanceError):
            form.form_text = "autre"  # type: ignore[misc]
