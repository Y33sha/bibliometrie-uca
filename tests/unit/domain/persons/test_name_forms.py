"""Tests unitaires du VO `PersonNameForm` et du calcul des formes de nom d'une personne."""

import dataclasses

import pytest

from domain.errors import ValidationError
from domain.persons.name_forms import (
    PersonNameForm,
    compute_person_name_forms,
    person_name_form_splits,
)


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


class TestPersonNameFormSplits:
    def test_chaque_forme_porte_son_decoupage(self) -> None:
        assert person_name_form_splits("Dupont", "Jean Michel") == {
            "jean michel dupont": ("dupont", "jean michel"),
            "dupont jean michel": ("dupont", "jean michel"),
            "j m dupont": ("dupont", "j m"),
            "dupont j m": ("dupont", "j m"),
            "jm dupont": ("dupont", "j m"),
            "dupont jm": ("dupont", "j m"),
        }

    def test_sans_prenom(self) -> None:
        assert person_name_form_splits("Dupont", "") == {"dupont": ("dupont", None)}

    def test_sans_nom(self) -> None:
        assert person_name_form_splits("", "Jean") == {}

    def test_formes_de_la_personne(self) -> None:
        assert compute_person_name_forms("Dupont", "Marie") == {
            "marie dupont",
            "dupont marie",
            "m dupont",
            "dupont m",
        }
