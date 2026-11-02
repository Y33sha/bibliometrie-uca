"""Origine du texte d'une adresse."""

import pytest

from domain.country_detection import CountryNames
from domain.normalize import normalize_text
from domain.structures.address_origin import AddressOrigin, address_origin

COUNTRY_NAMES = CountryNames({"france": "fr", "norway": "no", "spain": "es"})
STRUCTURE_NAMES = frozenset(
    normalize_text(name)
    for name in (
        "Université Clermont Auvergne [2017-2020]",
        "University of California, Berkeley",
        "University of Liverpool",
    )
)


def _origin(raw_text: str) -> AddressOrigin:
    return address_origin(
        raw_text,
        normalize_text(raw_text),
        structure_names=STRUCTURE_NAMES,
        country_names=COUNTRY_NAMES,
    )


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        (
            "IP - Institut Pascal (Campus Universitaire des Cézeaux, 63178 Aubière Cedex - France)",
            AddressOrigin.HAL_LABEL,
        ),
        ("Université Clermont Auvergne [2017-2020]", AddressOrigin.NAME_ONLY),
        ("University of California, Berkeley", AddressOrigin.NAME_ONLY),
        ("Institut Pascal, Université Clermont Auvergne, Aubière, France", AddressOrigin.RAW),
        ("Department of Pediatrics, University Hospital Rouen", AddressOrigin.RAW),
        ("Narvik University College (Norway)", AddressOrigin.HAL_LABEL),
        ("Laboratoire de Génétique CHU de Nancy Nancy France", AddressOrigin.RAW),
        ("Karlsruher Institut für Technologie", AddressOrigin.NAME_ONLY),
        ("Professeur", AddressOrigin.NAME_ONLY),
    ],
)
def test_origine(raw_text: str, expected: AddressOrigin):
    assert _origin(raw_text) is expected


def test_nom_de_structure_reconnu_apres_normalisation():
    assert _origin("UNIVERSITY OF LIVERPOOL") is AddressOrigin.NAME_ONLY


def test_parentheses_finales_sans_pays():
    assert _origin("Laboratoire de Mathématiques (LMBP)") is AddressOrigin.NAME_ONLY
