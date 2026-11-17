"""Adresse concaténée : plusieurs affiliations suivies chacune des initiales de leurs auteurs."""

import pytest

from domain.addresses.concatenation import is_concatenated


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        pytest.param(
            "From the Cleo Roberts Memory and Movement Clinic (D.S., P.C.), Banner Sun Health Research Institute, Sun City; Division of Neurology (J.K.L.-I.)",
            True,
            id="note d'affiliations",
        ),
        pytest.param(
            "Department of Medical Pharmacology, Lille (A.-S.R. and B.P.); Toulouse (M.S.-M., O.R.)",
            True,
            id="initiales composées",
        ),
        pytest.param("Grenoble University Hospital, France (P.D.)", False, id="un seul groupe"),
        pytest.param(
            "Univ Clermont Auvergne, CNRS, Inst Pascal, Clermont-Ferrand, France",
            False,
            id="sans initiales",
        ),
        pytest.param(
            "Centre Hospitalier Universitaire (CHU), Clermont-Ferrand (France)",
            False,
            id="sigles entre parenthèses",
        ),
    ],
)
def test_adresse_concatenee(raw_text, expected):
    assert is_concatenated(raw_text) is expected


def test_parenthese_non_fermee_sans_backtracking_exponentiel():
    assert is_concatenated("(" + "A." * 5000) is False
