"""Tests de `same_person_name` — prédicat « même personne » à la graphie près.

Cas réels tirés de l'audit du canal identifiant (`audit_identifier_consensus`).
"""

import pytest

from domain.persons.name_matching import same_person_name

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
]


@pytest.mark.parametrize(("a", "b"), SAME)
def test_same_person(a, b):
    assert same_person_name(a[0], a[1], b[0], b[1])
    assert same_person_name(b[0], b[1], a[0], a[1])  # symétrique


@pytest.mark.parametrize(("a", "b"), DISTINCT)
def test_distinct_person(a, b):
    assert not same_person_name(a[0], a[1], b[0], b[1])
    assert not same_person_name(b[0], b[1], a[0], a[1])
