"""Autres noms d'un éditeur (`domain.publishers.aliases`)."""

import pytest

from domain.publishers.aliases import compatible_publisher_names, prefix_holder


@pytest.mark.parametrize(
    ("named", "holder"),
    [
        ("Amer Physical Soc", "American Physical Society (APS)"),
        ("De Gruyter", "Walter de Gruyter"),
        ("John Libbey Eurotext", "JLE"),
        ("Karger Publishers", "S. Karger"),
        ("World Scientific Publishing", "World Scientific Pub Co Pte Ltd"),
    ],
)
def test_noms_du_meme_editeur(named, holder):
    assert compatible_publisher_names(named, holder)


@pytest.mark.parametrize(
    ("named", "holder"),
    [
        ("Taylor & Francis", "Informa UK Limited"),
        ("BioMed Central", "Springer"),
        ("Mary Ann Liebert", "SAGE Publications"),
    ],
)
def test_marques_et_rachats_restent_distincts(named, holder):
    assert not compatible_publisher_names(named, holder)


def test_titulaire_majoritaire():
    assert prefix_holder({1: 9, 2: 1}) == 1
    assert prefix_holder({1: 8, 2: 2}) is None
    assert prefix_holder({1: 4}) is None
