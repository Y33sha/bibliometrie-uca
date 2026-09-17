"""Tests de la comparaison et de la lecture des titres de revues (`domain.journals.titles`)."""

import pytest

from domain.journals.titles import names_a_dated_event, nested_titles


# Cas réels de la table journals.
@pytest.mark.parametrize(
    "title",
    [
        "NuFACT 2022",
        "2024 IEEE SENSORS",
        "Goldschmidt2023 abstracts",
        "Deutscher Kongress für Orthopädie und Unfallchirurgie (DKOU 2024)",
        "ICC 2019 - 2019 IEEE International Conference on Communications (ICC)",
        "2025 IEEE 101st Vehicular Technology Conference (VTC2025-Spring)",
    ],
)
def test_edition_datee(title):
    assert names_a_dated_event(title)


@pytest.mark.parametrize(
    "title",
    [
        "A Companion to Contemporary British and Irish Poetry, 1960–2015",
        "Christian-Muslim Relations 1500 - 1900",
        "22 Seiten (2023).",
        "1-26 (2021).",
        "Journal of high energy physics 2018(7)",
        "Journal of Modern Philosophy Volume 3 Issue 0 2021",
        "Physical Review Letters",
    ],
)
def test_pas_d_edition_datee(title):
    assert not names_a_dated_event(title)


def test_all_words_of_one_title_in_the_other():
    assert nested_titles("BMJ", "BMJ-BRITISH MEDICAL JOURNAL")
    assert nested_titles("Le Moyen Français", "Le moyen français/Le Moyen français")


def test_titles_of_two_publications():
    assert not nested_titles("Physical review C", "Physical review D")
    assert not nested_titles("Les Essentiels d'Hermès", "Hermès, La Revue")


def test_missing_title():
    assert not nested_titles(None, "Nature")
    assert not nested_titles("", "Nature")
