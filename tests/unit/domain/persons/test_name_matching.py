"""Tests de `names_compatible` — prédicat « même personne » à la graphie près.

Cas réels observés sur le canal identifiant (noms des porteurs d'une valeur vs son propriétaire) et sur les listes de collaboration.
"""

import pytest

from domain.persons.name_matching import (
    _edit_distance,
    first_name_initials,
    initials_extend,
    names_compatible,
)

SAME = [
    # Initiale, inversion nom/prénom.
    (("martin", "jean"), ("martin", "j")),
    (("martin", "jean"), ("jean", "martin")),
    # Initiales d'un prénom composé.
    (("bailly", "j l"), ("bailly", "jean luc")),
    # Initiales des deux côtés, patronyme entier en commun.
    (("martin", "j pierre"), ("martin", "jean p")),
    # Typo ou translittération du prénom (distance 1).
    (("beyssac", "erick"), ("beyssac", "eric")),
    (("khalil", "toufik"), ("khalil", "toufic")),
    (("durand", "denys"), ("durand", "denis")),
    (("lavrentiev", "alexey"), ("lavrentiev", "alexei")),
    # Typo du patronyme (transposition), prénom identique.
    (("blanquet doit", "stephanie"), ("blanquet diot", "stephanie")),
    # Année de naissance d'une signature SUDOC, retirée.
    (("chiari 1977", "sophie"), ("chiari", "sophie")),
    # Graphie proche du patronyme et initiale du prénom, cumulées.
    (("mueller", "roman"), ("muller", "r")),
    # Formes normalisées entières, dont l'ordre des parties dépend de la source.
    (("dupont jean", ""), ("jean dupont", "")),
    (("mueller roman", ""), ("r muller", "")),
    (("j bielcikova", ""), ("bielckova j", "")),
]

DISTINCT = [
    # Homonyme de patronyme, prénom franchement autre.
    (("chanal", "herve"), ("chanal", "helene")),
    (("verdier", "cyril"), ("verdier", "cecile")),
    (("duclos", "martine"), ("duclos", "michel")),
    # Deux initiales différentes (pas de signal de distance).
    (("zhang", "b"), ("zhang", "x")),
    # Graphie proche du patronyme, deux initiales différentes.
    (("mueller", "b"), ("muller", "x")),
    # Distance 2 sur le prénom : tenu pour distinct (choix conservateur).
    (("bonin", "patrick"), ("bonin", "patricia")),
    # Patronyme différent (nom marié : hors périmètre du prédicat, réglé
    # ailleurs par les formes de nom).
    (("houssais", "sarah"), ("porteboeuf", "sarah")),
    # Sans aucun rapport (capture franche).
    (("bouchhar", "n"), ("bouaouda", "k")),
    # Patronyme absent d'un côté : le prénom proche ne suffit pas.
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
