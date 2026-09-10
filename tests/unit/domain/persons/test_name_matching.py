"""Tests de `same_person_name` — prédicat « même personne » à la graphie près.

Cas réels observés sur le canal identifiant (noms des porteurs d'une valeur vs son propriétaire).
"""

import pytest

from domain.persons.name_matching import (
    _edit_distance,
    names_compatible,
    same_person_name,
)

SAME = [
    # Cas déjà couverts par names_compatible : initiale, inversion nom/prénom.
    (("martin", "jean"), ("martin", "j")),
    (("martin", "jean"), ("jean", "martin")),
    # Concaténation du prénom.
    (("gannoun", "abdel mouhcine"), ("gannoun", "abdelmouhcine")),
    (("zhu", "zheng ze"), ("zhu", "zhengze")),
    (("kolovi", "so fia"), ("kolovi", "sofia")),
    # Particule / composé accolé (patronyme).
    (("st paul", "nicolas"), ("stpaul", "nicolas")),
    (("le roy", "pascale"), ("leroy", "pascale")),
    # Typo ou translittération du prénom (distance 1).
    (("beyssac", "erick"), ("beyssac", "eric")),
    (("khalil", "toufik"), ("khalil", "toufic")),
    (("durand", "denys"), ("durand", "denis")),
    (("lavrentiev", "alexey"), ("lavrentiev", "alexei")),
    # Typo du patronyme (transposition), prénom identique.
    (("blanquet doit", "stephanie"), ("blanquet diot", "stephanie")),
    # Particules accolées : plusieurs espaces retirés.
    (("de la fontaine", "jean"), ("delafontaine", "jean")),
    # Année de naissance d'une signature SUDOC, retirée de la concaténation.
    (("le roy 1977", "pascale"), ("leroy", "pascale")),
]

DISTINCT = [
    # Homonyme de patronyme, prénom franchement autre.
    (("chanal", "herve"), ("chanal", "helene")),
    (("verdier", "cyril"), ("verdier", "cecile")),
    (("duclos", "martine"), ("duclos", "michel")),
    # Deux initiales différentes (pas de signal de distance).
    (("zhang", "b"), ("zhang", "x")),
    # Distance 2 sur le prénom : tenu pour distinct (choix conservateur).
    (("bonin", "patrick"), ("bonin", "patricia")),
    # Patronyme différent (nom marié : hors périmètre du prédicat, réglé
    # ailleurs par les formes de nom).
    (("houssais", "sarah"), ("porteboeuf", "sarah")),
    # Sans aucun rapport (capture franche).
    (("bouchhar", "n"), ("bouaouda", "k")),
    # Patronyme absent d'un côté : le prénom proche ne suffit pas.
    (("", "eric"), ("beyssac", "erick")),
]


@pytest.mark.parametrize(("a", "b"), SAME)
def test_same_person(a, b):
    assert same_person_name(a[0], a[1], b[0], b[1])
    assert same_person_name(b[0], b[1], a[0], a[1])  # symétrique


@pytest.mark.parametrize(("a", "b"), DISTINCT)
def test_distinct_person(a, b):
    assert not same_person_name(a[0], a[1], b[0], b[1])
    assert not same_person_name(b[0], b[1], a[0], a[1])


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
