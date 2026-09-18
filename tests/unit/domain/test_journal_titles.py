"""Tests de la comparaison et de la lecture des titres de revues (`domain.journals.titles`)."""

import pytest

from domain.journals.titles import (
    compatible_titles,
    names_a_dated_event,
    names_proceedings,
    nested_titles,
)


# Cas réels de la table journals.
def test_titre_d_actes():
    assert names_proceedings("Proceedings of the Samahang Pisika ng Pilipinas")
    assert names_proceedings(
        "Proceedings of the 36th Annual Conference of the European Association of Cognitive Ergonomics"
    )


@pytest.mark.parametrize(
    "title",
    [
        "Proceedings of the Wesley Historical Society",
        "Proceedings of the National Academy of Sciences",
        "Proceedings of the Institution of Civil Engineers - Structures and Buildings",
        "Physical Review Letters",
    ],
)
def test_revue_d_une_societe_savante(title):
    assert not names_proceedings(title)


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


# Cas réels : revues portées par les enregistrements d'une même publication.
@pytest.mark.parametrize(
    ("full", "short"),
    [
        ("Physical Review Letters", "Phys.Rev.Lett."),
        ("The European Physical Journal C", "Eur.Phys.J.C"),
        ("Physics Reports", "Phys.Rept."),
        ("Critical Care Medicine", "Crit Care Med"),
        ("Monthly Notices of the Royal Astronomical Society", "Mon.Not.Roy.Astron.Soc."),
        ("Journal of Instrumentation", "JINST"),
        ("Journal of Cosmology and Astroparticle Physics", "JCAP"),
        ("Highlights in High-Energy Physics", "HiHEP"),
        ("The European Physical Journal Special Topics", "Eur.Phys.J.ST"),
        ("Studia Universitatis Babeș-Bolyai Philologia", "STUDIA UBB PHILOLOGIA"),
        ("Engineering Applications of Artificial Intelligence", "Eng. Appl. of AI"),
        ("Revue d'histoire sociale", "Revue d’histoire sociale"),
        ("Physical review. D/Physical review. D.", "Phys.Rev.D"),
        ("Notos - Espaces de la création : arts, écritures, utopies", "Notos"),
        ("Medicine (Baltimore)", "Medicine"),
    ],
)
def test_compatible_titles(full, short):
    assert compatible_titles(full, short)
    assert compatible_titles(short, full)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Microscopy", "Microscopy Today"),
        ("JAMA", "JAMA Cardiology"),
        ("Timing & Time Perception", "Timing & Time Perception Reviews"),
        ("Pharmacia", "Pharmacia Actualites"),
        ("Bulletin du Cancer", "Bulletin du Cancer. Radiotherapie"),
        ("Journal of the Optical Society of America A", "Optica"),
        ("Physical Review A", "Physical Review D"),
        ("Nuclear Physics A", "Nuclear Physics B"),
    ],
)
def test_titles_of_distinct_journals(a, b):
    assert not compatible_titles(a, b)
