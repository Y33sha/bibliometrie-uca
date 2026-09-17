"""Tests de la clé de rapprochement des noms d'éditeurs (`domain.publishers.names`)."""

import pytest

from domain.publishers.names import publisher_name_key


# Cas réels de la table publishers.
@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Elsevier BV", "elsevier"),
        ("Elsevier [1977-....]", "elsevier"),
        ("Elsevier on behalf of the American College of Cardiology Foundation", "elsevier"),
        ("Elsevier (Amsterdam, Nederland) [2020-....]", "elsevier"),
        ("TAYLOR & FRANCIS LTD", "taylor francis"),
        ("Taylor & Francis (Routledge)", "taylor francis"),
        ("Walter de Gruyter GmbH & Co KG", "walter de gruyter"),
        ("Nature Publishing Group, 2009-", "nature publishing group"),
        ("INRA (2009-2019)", "inra"),
    ],
)
def test_bruit_retire(name, key):
    assert publisher_name_key(name) == key


def test_sigle_seul_garde_sa_precision():
    assert publisher_name_key("AIMS (Association internationale de management stratégique)") == (
        "aims association internationale de management strategique"
    )


def test_for_the_fait_partie_du_nom():
    assert publisher_name_key("Association for the Advancement of Artificial Intelligence") == (
        "association for the advancement of artificial intelligence"
    )
