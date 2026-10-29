"""Tests de `names_compatible` : deux noms désignent la même personne, à la graphie près.

Les cas viennent des données réelles : noms des contributions sources qui ont un identifiant de personne, comparés au nom de la personne à qui il est attribué ; listes de collaboration.
"""

import pytest

from domain.persons.name_matching import (
    _edit_distance,
    family_name_splits,
    first_name_initials,
    full_first_name_extends,
    initials_extend,
    names_compatible,
)

SAME = [
    # Initiale, inversion nom/prénom.
    (("martin", "jean"), ("martin", "j")),
    (("martin", "jean"), ("jean", "martin")),
    # Initiales d'un prénom composé.
    (("bailly", "j l"), ("bailly", "jean luc")),
    # Initiales des deux côtés, nom de famille entier en commun.
    (("martin", "j pierre"), ("martin", "jean p")),
    # Faute de frappe ou translittération du prénom (distance 1).
    (("beyssac", "erick"), ("beyssac", "eric")),
    (("khalil", "toufik"), ("khalil", "toufic")),
    (("durand", "denys"), ("durand", "denis")),
    (("lavrentiev", "alexey"), ("lavrentiev", "alexei")),
    # Faute de frappe du nom de famille (transposition), prénom identique.
    (("blanquet doit", "stephanie"), ("blanquet diot", "stephanie")),
    # Année de naissance d'une contribution source du Sudoc, retirée.
    (("chiari 1977", "sophie"), ("chiari", "sophie")),
    # Graphie proche du nom de famille et initiale du prénom, cumulées.
    (("mueller", "roman"), ("muller", "r")),
    # Formes normalisées entières, dont l'ordre des parties dépend de la source.
    (("dupont jean", ""), ("jean dupont", "")),
    (("mueller roman", ""), ("r muller", "")),
    (("j bielcikova", ""), ("bielckova j", "")),
]

DISTINCT = [
    # Même nom de famille, prénom franchement autre.
    (("chanal", "herve"), ("chanal", "helene")),
    (("verdier", "cyril"), ("verdier", "cecile")),
    (("duclos", "martine"), ("duclos", "michel")),
    # Deux initiales différentes.
    (("zhang", "b"), ("zhang", "x")),
    # Graphie proche du nom de famille, deux initiales différentes.
    (("mueller", "b"), ("muller", "x")),
    # Distance 2 sur le prénom : personnes distinctes.
    (("bonin", "patrick"), ("bonin", "patricia")),
    # Nom de famille différent (nom d'usage après mariage, traité par les formes de nom).
    (("houssais", "sarah"), ("porteboeuf", "sarah")),
    # Noms sans rapport.
    (("bouchhar", "n"), ("bouaouda", "k")),
    # Nom de famille absent d'un côté : le prénom proche ne suffit pas.
    (("", "eric"), ("beyssac", "erick")),
    # Voisins alphabétiques d'une liste de collaboration.
    (("t dado", ""), ("s dahbi", "")),
    (("tulin varol", ""), ("d varouchas", "")),
    # Une initiale couvre un seul mot de l'autre nom.
    (("s solomon", ""), ("sanya solodkov", "")),
    (("s solomon", ""), ("sukanya sinha", "")),
    # Un appariement par initiale exige deux mots entiers appariés.
    (("s pierre", ""), ("p simon", "")),
    (("solomon", "s"), ("spinali", "s")),
    (("j m", ""), ("jean martin", "")),
    # Un nom n'est jamais réduit à un seul mot accolé que couvrirait une initiale de l'autre.
    (("m morandin", ""), ("monteil", "stephane")),
    (("m j morello", ""), ("monteil", "stephane")),
    (("mu", "z m"), ("monteil", "s")),
    (("merk", "m"), ("monteil", "s")),
]


@pytest.mark.parametrize(("a", "b"), SAME)
def test_same_person(a, b):
    assert names_compatible(a[0], a[1], b[0], b[1])
    assert names_compatible(b[0], b[1], a[0], a[1])  # symétrique


@pytest.mark.parametrize(("a", "b"), DISTINCT)
def test_distinct_person(a, b):
    assert not names_compatible(a[0], a[1], b[0], b[1])
    assert not names_compatible(b[0], b[1], a[0], a[1])


def test_un_nom_vide_n_est_compatible_avec_aucun_autre():
    assert not names_compatible("", "", "martin", "jean")
    assert not names_compatible("martin", "jean", "", "")


@pytest.mark.parametrize(
    ("a", "b", "distance"),
    [
        ("abc", "abc", 0),
        ("", "", 0),
        ("a", "", 1),
        ("", "ab", 2),
        ("abc", "", 3),
        ("a", "b", 1),
        ("ab", "abc", 1),
        ("abc", "ab", 1),
        ("ab", "b", 1),
        ("ab", "ba", 1),
        ("abc", "acb", 1),
        ("xab", "xba", 1),
        ("doit", "diot", 1),
        ("abcd", "badc", 2),
        ("kitten", "sitting", 3),
        # Deux lettres ajoutées, sans transposition possible.
        ("a", "aaa", 2),
        # Une lettre insérée entre deux lettres transposées : la restriction « optimal string alignment » compte 3.
        ("ca", "abc", 3),
    ],
)
def test_distance_d_edition(a, b, distance):
    assert _edit_distance(a, b) == distance
    assert _edit_distance(b, a) == distance


@pytest.mark.parametrize(
    ("first_name", "initials"),
    [
        ("A.", ("a",)),
        ("J.-P.", ("j", "p")),
        ("A M", ("a", "m")),
        ("JP", ("j", "p")),
        ("Abdellah", None),
        ("Denis M.", None),
        ("", None),
    ],
)
def test_initiales_d_un_prenom(first_name, initials):
    assert first_name_initials(first_name) == initials


@pytest.mark.parametrize(
    ("initials", "first_name", "extend"),
    [
        (("a",), "Abdul-Majeed", True),
        (("a", "m"), "Abdul-Majeed", True),
        (("d",), "Denis M.", True),
        (("j",), "J.-P.", True),
        (("h",), "Bo-Hyung", False),
        (("c", "g"), "Chloé", False),
        (("a",), "", False),
    ],
)
def test_initiales_qui_commencent_un_prenom(initials, first_name, extend):
    assert initials_extend(initials, first_name) is extend


@pytest.mark.parametrize(
    ("initials", "first_name", "extends"),
    [
        (("a",), "Abdellah", True),
        (("a", "m"), "Abdul-Majeed", True),
        (("j",), "J.-P.", False),
        (("a",), "A. B.", False),
        (("h",), "Bo-Hyung", False),
        (("a",), "", False),
    ],
)
def test_prenom_plein_qui_prolonge_des_initiales(initials, first_name, extends):
    assert full_first_name_extends(initials, first_name) is extends


@pytest.mark.parametrize(
    ("raw", "splits"),
    [
        (
            "Florence Caldefie Chezet",
            [("Caldefie Chezet", "Florence"), ("Chezet", "Florence Caldefie")],
        ),
        ("Jean Martin", [("Martin", "Jean")]),
        ("Caldefie-Chezet, F.", [("Caldefie-Chezet", "F.")]),
        ("Martin", [("Martin", "")]),
        ("", []),
    ],
)
def test_decoupages_d_un_nom_de_contributeur(raw, splits):
    assert family_name_splits(raw) == splits
