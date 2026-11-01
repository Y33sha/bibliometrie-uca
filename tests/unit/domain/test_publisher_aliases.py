"""Autres noms d'un éditeur (`domain.publishers.aliases`)."""

import pytest

from domain.publishers.aliases import (
    NamedPublisher,
    compatible_publisher_names,
    core_publisher_name,
    prefix_holder,
    same_name_merges,
)


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


def test_nom_reduit():
    assert core_publisher_name("Brepols Publ") == core_publisher_name("Brepols Publishers")
    assert core_publisher_name("The Publishers") == ""


def test_meme_nom_reduit_rejoint_le_titulaire_de_prefixe():
    publishers = [
        NamedPublisher(1, "Brepols Publishers", 40, False),
        NamedPublisher(2, "Brepols Publ", 3, True),
        NamedPublisher(3, "Brepols", 5, False),
    ]
    assert same_name_merges(publishers) == [(1, 2), (3, 2)]


def test_sans_titulaire_le_plus_nomme_puis_le_plus_ancien():
    assert same_name_merges(
        [NamedPublisher(1, "Brepols Publ", 3, False), NamedPublisher(2, "Brepols", 8, False)]
    ) == [(1, 2)]
    assert same_name_merges(
        [NamedPublisher(1, "Brepols Publ", 3, False), NamedPublisher(2, "Brepols", 3, False)]
    ) == [(2, 1)]


def test_plusieurs_titulaires_ou_nom_reduit_courant_restent_en_l_etat():
    assert not same_name_merges(
        [NamedPublisher(1, "Brepols Publ", 3, True), NamedPublisher(2, "Brepols", 8, True)]
    )
    assert not same_name_merges(
        [
            NamedPublisher(1, "Academic Publishers", 3, False),
            NamedPublisher(2, "Academic Publications", 8, False),
        ]
    )
