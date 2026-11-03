"""Tests de la comparaison des titres (`domain.title_comparison`)."""

import pytest

from domain.title_comparison import compatible_titles, nested_titles


def test_all_words_of_one_title_in_the_other():
    assert nested_titles("BMJ", "BMJ-BRITISH MEDICAL JOURNAL")
    assert nested_titles("Le Moyen Français", "Le moyen français/Le Moyen français")


def test_titles_of_two_publications():
    assert not nested_titles("Physical review C", "Physical review D")
    assert not nested_titles("Les Essentiels d'Hermès", "Hermès, La Revue")


def test_missing_title():
    assert not nested_titles(None, "Nature")
    assert not nested_titles("", "Nature")


# Cas réels : revues données par les enregistrements sources d'une même publication.
@pytest.mark.parametrize(
    ("full", "short"),
    [
        ("Physical Review Letters", "Phys.Rev.Lett."),
        ("The European Physical Journal C", "Eur.Phys.J.C"),
        ("Physics Reports", "Phys.Rept."),
        ("Critical Care Medicine", "Crit Care Med"),
        (
            "Monthly Notices of the Royal Astronomical Society",
            "Mon.Not.Roy.Astron.Soc.",
        ),
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
def test_titles_of_distinct_serials(a, b):
    assert not compatible_titles(a, b)
