"""Origine du texte d'une adresse."""

import pytest

from domain.addresses.address_origin import AddressOrigin, OriginReferentials, address_origin
from domain.addresses.country_detection import CountryNames
from domain.normalize import normalize_text

REFERENTIALS = OriginReferentials.from_names(
    (
        "Université Clermont Auvergne [2017-2020]",
        "University of California, Berkeley",
        "University of Liverpool",
        "CHU Clermont-Ferrand",
        "Waseda University [Tokyo]",
    ),
    city_names=("tokyo", "braga", "clermont ferrand"),
    country_names=CountryNames(
        {"france": "fr", "norway": "no", "japan": "jp", "portugal": "pt", "belgium": "be"}
    ),
)


def _origin(raw_text: str) -> AddressOrigin:
    return address_origin(raw_text, normalize_text(raw_text), REFERENTIALS)


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        (
            "IP - Institut Pascal (Campus Universitaire des Cézeaux, 63178 Aubière Cedex - France)",
            AddressOrigin.HAL_LABEL,
        ),
        ("University of Mons [Belgium]", AddressOrigin.HAL_LABEL),
        ("ICVS/3B's—PT Government Associate Laboratory [Braga, Portugal]", AddressOrigin.HAL_LABEL),
        (
            "Service de Gynécologie [CHU Clermont-Ferrand], Clermont-Ferrand, France",
            AddressOrigin.HAL_LABEL,
        ),
        ("LIMOS, UCA [2017-2020], CNRS", AddressOrigin.HAL_LABEL),
        ("Université Clermont Auvergne [2017-2020]", AddressOrigin.HAL_LABEL),
        ("University of California, Berkeley", AddressOrigin.NAME_ONLY),
        ("CHU Clermont-Ferrand, France", AddressOrigin.NAME_ONLY),
        ("Waseda University, Tokyo, Japan", AddressOrigin.RAW),
        ("CHU Clermont Ferrand, Clermont Ferrand, France", AddressOrigin.RAW),
        ("Institut Pascal, Université Clermont Auvergne, Aubière, France", AddressOrigin.RAW),
        ("Department of Pediatrics, University Hospital Rouen", AddressOrigin.RAW),
        (
            "Department of Gastroenterology, Institut des Maladies de l'appareil Digestif [IMAD], Nantes, France",
            AddressOrigin.RAW,
        ),
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


def test_crochets_vides_apres_normalisation():
    assert (
        _origin("Université Clermont Auvergne, « […] le signe », Aubière, France")
        is AddressOrigin.RAW
    )
