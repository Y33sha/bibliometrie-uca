"""Modèle open access d'une revue l'année de parution d'une publication."""

import pytest

from domain.serials.oa_model_history import OaModelHistory, doaj_year
from domain.serials.serial import OaModel


def _history(
    model: OaModel | None = OaModel.FULL_OA,
    *,
    is_oa: bool | None = None,
    flip: int | None = None,
    doaj: int | None = None,
) -> OaModelHistory:
    return OaModelHistory(model, is_oa, flip, doaj)


@pytest.mark.parametrize("year", [1990, 2024, None])
def test_revue_nee_en_open_access_integral(year):
    assert _history(is_oa=True).model_at(year) == OaModel.FULL_OA


@pytest.mark.parametrize(
    ("year", "expected"), [(2010, OaModel.SUBSCRIPTION), (2011, OaModel.FULL_OA)]
)
def test_revue_passee_a_l_open_access_integral(year, expected):
    assert _history(is_oa=True, flip=2011).model_at(year) == expected


def test_openalex_prime_sur_le_doaj():
    assert _history(is_oa=True, flip=2011, doaj=2005).model_at(2008) == OaModel.SUBSCRIPTION


@pytest.mark.parametrize("is_oa", [False, None])
def test_annee_du_doaj_hors_open_access_d_openalex(is_oa):
    history = _history(OaModel.DIAMOND, is_oa=is_oa, doaj=2015)
    assert (history.model_at(2014), history.model_at(2015)) == (
        OaModel.SUBSCRIPTION,
        OaModel.DIAMOND,
    )


def test_annee_du_passage_inconnue():
    assert _history(is_oa=False).model_at(2020) is None


def test_annee_de_parution_inconnue():
    assert _history(is_oa=True, flip=2011).model_at(None) is None


@pytest.mark.parametrize("model", [OaModel.SUBSCRIPTION, None])
def test_revue_hors_open_access_integral(model):
    assert _history(model).model_at(2020) == model


@pytest.mark.parametrize(
    ("value", "expected"), [("2006", 2006), ("2006-01", None), ("", None), (None, None)]
)
def test_annee_du_doaj(value, expected):
    assert doaj_year(value) == expected
