"""Lecture d'un code pays reçu : `domain.countries.normalize_country_code`."""

import pytest

from domain.countries import FRENCH_OVERSEAS_CODES, NO_COUNTRY_CODE, normalize_country_code


@pytest.mark.parametrize(("raw", "expected"), [("FR", "fr"), (" be ", "be"), ("de", "de")])
def test_un_code_a_deux_lettres_est_ramene_en_minuscules(raw, expected):
    assert normalize_country_code(raw) == expected


@pytest.mark.parametrize("raw", sorted(FRENCH_OVERSEAS_CODES) + ["GP", " nc "])
def test_un_code_de_l_outre_mer_devient_la_france(raw):
    assert normalize_country_code(raw) == "fr"


@pytest.mark.parametrize("raw", [None, "", "--", "fra", "f1"])
def test_une_autre_forme_est_refusee(raw):
    assert normalize_country_code(raw) is None


@pytest.mark.parametrize("raw", [NO_COUNTRY_CODE, NO_COUNTRY_CODE.upper()])
def test_le_code_reserve_est_refuse(raw):
    assert normalize_country_code(raw) is None
