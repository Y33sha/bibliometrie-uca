"""Tests unitaires du VO `PersonNameForm` et du calcul des formes de nom d'une personne."""

import dataclasses

import pytest

from domain.errors import ValidationError
from domain.persons.name_forms import (
    PersonNameForm,
    compute_person_name_forms,
    signature_name_forms,
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


class TestComputePersonNameForms:
    def test_prenom_nom_et_initiales_nom(self) -> None:
        assert compute_person_name_forms("Dupont", "Jean Michel") == {
            "jean michel dupont",
            "j m dupont",
        }

    def test_prenom_en_initiales_collees(self) -> None:
        """Prénom normalisé comme celui des signatures : « JP » donne « j p »."""
        assert compute_person_name_forms("Dupont", "JP") == {"j p dupont"}

    def test_accents(self) -> None:
        assert compute_person_name_forms("Bensoussan", "Népomucène") == {
            "nepomucene bensoussan",
            "n bensoussan",
        }

    def test_annee_de_naissance_retiree(self) -> None:
        """Une fiche créée d'après une forme d'autorité porte l'année de naissance."""
        assert compute_person_name_forms("Chométy", "Philippe 1973-") == {
            "philippe chomety",
            "p chomety",
        }

    def test_sans_prenom(self) -> None:
        assert compute_person_name_forms("Dupont", "") == {"dupont"}

    def test_sans_nom(self) -> None:
        assert compute_person_name_forms("", "Jean") == set()


class TestSignatureNameForms:
    def test_prenom_nom_puis_nom_prenom(self) -> None:
        assert signature_name_forms("dupont", "marie") == ("marie dupont", "dupont marie")

    def test_sans_prenom(self) -> None:
        assert signature_name_forms("dupont", None) == ("dupont",)
