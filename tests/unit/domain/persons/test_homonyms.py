"""Contribution d'une publication rejetée qui rejoint l'homonyme de la personne (`domain.persons.homonyms`)."""

from domain.persons.homonyms import homonym_contribution

MASSARD = ("massard", "christophe")


def test_la_seule_contribution_au_nom_de_la_personne_rejoint_l_homonyme():
    contributions = {1: [("durand", "paul")], 2: [("massard", "c"), ("massard", "christophe")]}

    assert homonym_contribution(MASSARD, contributions) == 2


def test_aucune_contribution_au_nom_de_la_personne_ne_donne_rien():
    assert homonym_contribution(MASSARD, {1: [("durand", "paul")]}) is None


def test_deux_contributions_au_nom_de_la_personne_ne_donnent_rien():
    contributions = {1: [("massard", "christophe")], 2: [("massard", "c")]}

    assert homonym_contribution(MASSARD, contributions) is None
