"""Origine du texte d'une adresse."""

import pytest

from domain.addresses.address_origin import AddressOrigin, OriginReferentials, address_origin
from domain.addresses.country_detection import CountryNames
from domain.normalize import normalize_text

REFERENTIALS = OriginReferentials.from_names(
    (
        "Université Clermont Auvergne [2017-2020]",
        "University of California, Berkeley",
        "CHU Clermont-Ferrand",
        "Waseda University [Tokyo]",
    ),
    city_names=("tokyo", "braga", "clermont ferrand"),
    country_names=CountryNames(
        {"france": "fr", "norway": "no", "japan": "jp", "portugal": "pt", "belgium": "be"}
    ),
)


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        pytest.param(
            "IP - Institut Pascal (Campus Universitaire des Cézeaux, 63178 Aubière Cedex - France)",
            AddressOrigin.HAL_LABEL,
            id="libellé HAL complet",
        ),
        pytest.param(
            "University of Mons [Belgium]", AddressOrigin.HAL_LABEL, id="pays entre crochets"
        ),
        pytest.param(
            "ICVS/3B's—PT Government Associate Laboratory [Braga, Portugal]",
            AddressOrigin.HAL_LABEL,
            id="ville et pays entre crochets",
        ),
        pytest.param(
            "Service de Gynécologie [CHU Clermont-Ferrand], Clermont-Ferrand, France",
            AddressOrigin.HAL_LABEL,
            id="nom de structure entre crochets",
        ),
        pytest.param(
            "LIMOS, UCA [2017-2020], CNRS",
            AddressOrigin.HAL_LABEL,
            id="période entre crochets avec virgules",
        ),
        pytest.param(
            "Université Clermont Auvergne [2017-2020]",
            AddressOrigin.HAL_LABEL,
            id="période entre crochets d'un nom de structure",
        ),
        pytest.param(
            "Department of Gastroenterology, Institut des Maladies de l'appareil Digestif [IMAD], Nantes, France",
            AddressOrigin.RAW,
            id="sigle entre crochets",
        ),
        pytest.param(
            "Université Clermont Auvergne, « […] le signe », Aubière, France",
            AddressOrigin.RAW,
            id="crochets vides après normalisation",
        ),
        pytest.param(
            "University of California, Berkeley",
            AddressOrigin.NAME_ONLY,
            id="nom de structure avec virgule",
        ),
        pytest.param(
            "CHU Clermont-Ferrand, France", AddressOrigin.NAME_ONLY, id="nom de structure et pays"
        ),
        pytest.param(
            "Waseda University, Tokyo, Japan",
            AddressOrigin.RAW,
            id="nom de structure, ville et pays",
        ),
        pytest.param(
            "Narvik University College (Norway)",
            AddressOrigin.HAL_LABEL,
            id="pays entre parenthèses finales",
        ),
        pytest.param(
            "GePEB - Génie des Procédés, Energétique et Biosystèmes (France)",
            AddressOrigin.HAL_LABEL,
            id="pays entre parenthèses finales avec virgule",
        ),
        pytest.param(
            "Laboratoire de Mathématiques (LMBP)",
            AddressOrigin.NAME_ONLY,
            id="sigle entre parenthèses finales",
        ),
        pytest.param(
            "Department of Pediatrics, University Hospital Rouen", AddressOrigin.RAW, id="virgule"
        ),
        pytest.param(
            "Laboratoire de Génétique CHU de Nancy Nancy France",
            AddressOrigin.RAW,
            id="pays final sans virgule",
        ),
        pytest.param(
            "Karlsruher Institut für Technologie", AddressOrigin.NAME_ONLY, id="nom inconnu"
        ),
    ],
)
def test_origine(raw_text: str, expected: AddressOrigin):
    assert address_origin(raw_text, normalize_text(raw_text), REFERENTIALS) is expected
