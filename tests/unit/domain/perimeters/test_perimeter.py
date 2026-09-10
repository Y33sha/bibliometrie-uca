"""Invariants de l'entité `Perimeter` : code et nom non vides."""

import pytest

from domain.errors import ValidationError
from domain.perimeters.perimeter import Perimeter


def _perimetre() -> Perimeter:
    return Perimeter.create(code="UCA", name="Université Clermont Auvergne", root_structure_ids=[1])


def test_create_pose_les_champs():
    assert Perimeter.create(code="UCA", name="UCA", root_structure_ids=[1, 2]) == Perimeter(
        id=None, code="UCA", name="UCA", root_structure_ids=(1, 2)
    )


@pytest.mark.parametrize(
    ("code", "name", "champ"),
    [("", "UCA", "code"), ("   ", "UCA", "code"), ("UCA", "", "nom"), ("UCA", "   ", "nom")],
)
def test_create_refuse_un_champ_vide(code, name, champ):
    with pytest.raises(ValidationError, match=f"Le {champ} du périmètre est requis"):
        Perimeter.create(code=code, name=name, root_structure_ids=[])


def test_set_name_renomme():
    perimetre = _perimetre()
    perimetre.set_name("Clermont Auvergne")
    assert perimetre.name == "Clermont Auvergne"


def test_set_name_refuse_un_nom_absent():
    with pytest.raises(ValidationError, match="Le nom du périmètre est requis"):
        _perimetre().set_name(None)


def test_set_root_structure_ids_absent_vide_les_racines():
    perimetre = _perimetre()
    perimetre.set_root_structure_ids(None)
    assert perimetre.root_structure_ids == ()
