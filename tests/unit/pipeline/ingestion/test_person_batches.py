"""Composition des lots du moissonnage par personne : réunion des personnes qui copublient."""

from __future__ import annotations

from pipeline.ingestion.common.person_batches import compose_batches


def test_reunit_les_personnes_qui_copublient():
    """Les personnes 1 et 3 cosignent les publications 10 et 11, les personnes 2 et 4 la publication 20."""
    publications = {
        1: frozenset({10, 11, 12}),
        2: frozenset({20, 21}),
        3: frozenset({10, 11}),
        4: frozenset({20}),
    }

    assert compose_batches([1, 2, 3, 4], publications, {}, 2) == [[1, 3], [2, 4]]


def test_prefere_a_egalite_la_personne_qui_ajoute_le_moins_de_publications():
    publications = {1: frozenset({10, 11}), 2: frozenset({10, 30, 31}), 3: frozenset({10})}

    assert compose_batches([1, 2, 3], publications, {}, 2) == [[2, 3], [1]]


def test_sans_copublication_suit_le_nombre_de_publications_puis_l_unite():
    """Sans publication commune, les personnes se suivent par nombre de publications décroissant, puis par unité, les personnes sans unité en dernier."""
    publications = {5: frozenset({50, 51})}
    units = {1: "U2", 2: None, 3: "U1", 4: "U2"}

    assert compose_batches([1, 2, 3, 4, 5], publications, units, 2) == [[5, 3], [1, 4], [2]]
