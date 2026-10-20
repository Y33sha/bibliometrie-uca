"""Reconnaissance d'un nom de contribution source collective."""

import pytest

from domain.persons.collective_names import is_collective_name


@pytest.mark.parametrize(
    "name",
    [
        "ATLAS Collaboration",
        "Collaborations, OPAL",
        "Le French Gut Consortium",
        "for the PREDISTIM working group",
        "The ESUB-MG Study Group",
        "Groupe d'Etude Thérapeutique des Affections Inflammatoires du Tube Digestif (GETAID)",
        "Genoscope Technical Team",
        "Uruguayan Invasive Fungal Infection Network",
        "Réseau AChro-Puce",
        "NADEGE Investigators",
        "on behalf of the DETERMINE Investigators",
        "ENPEN Study Collaborators",
        "French Society of Bone Marrow Transplantation and Cellular Therapy",
        "In vitro tests for Drug Allergy Task Force of EAACI",
        "Et Al.",
        "et al",
        "Die Redaktion",
        "International Monetary Fund. African Dept.",
        "École Normale Supérieure de Lyon",
        "Université Clermont Auvergne",
        "Universität Hamburg, Germany",
        "Rutherford Appleton Laboratory",
        "The PLOS ONE Editors",
    ],
)
def test_reconnait_un_collectif(name):
    assert is_collective_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "Antonio Comite",
        "Tony Affolder",
        "A. Nedelcu plus co-authors",
        "R. Barate et al.",
        "François Fund",
        "Sebastian Bank",
        "",
        None,
    ],
)
def test_garde_les_personnes(name):
    """« Comite » est aussi un nom de famille. Une personne suivie de ses co-auteurs reste une personne."""
    assert not is_collective_name(name)
