"""Tests de la comparaison des titres de revues (`domain.journals.titles`)."""

from domain.journals.titles import nested_titles


def test_all_words_of_one_title_in_the_other():
    assert nested_titles("BMJ", "BMJ-BRITISH MEDICAL JOURNAL")
    assert nested_titles("Le Moyen Français", "Le moyen français/Le Moyen français")


def test_titles_of_two_publications():
    assert not nested_titles("Physical review C", "Physical review D")
    assert not nested_titles("Les Essentiels d'Hermès", "Hermès, La Revue")


def test_missing_title():
    assert not nested_titles(None, "Nature")
    assert not nested_titles("", "Nature")
