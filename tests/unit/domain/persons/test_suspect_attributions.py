"""Tests de la détection des attributions suspectes : poids des indices, clusters signalés, ressemblance avec les publications rejetées."""

from domain.persons.suspect_attributions import (
    ClueFamily,
    ClueFrequencies,
    PublicationClues,
    edge_weights,
    resembles_rejected,
    signaled_clusters,
)
from domain.persons.tie_break import ContributionContext

_FREQUENCIES = ClueFrequencies(
    publication_count=10_000,
    counts={ClueFamily.SERIAL: {1: 5000, 2: 10}, ClueFamily.LABORATORY: {7: 100}},
)


def _publication(contribution_id, *clues, anchored=False):
    return PublicationClues(contribution_id, anchored, frozenset(clues))


def _labels(*labels):
    """Renvoie une partition qui attribue d'avance un cluster à chaque sommet."""

    def partition(n, _weights, _resolution):
        assert n == len(labels)
        return labels

    return partition


_LAB = (ClueFamily.LABORATORY, 7)
_RARE_SERIAL = (ClueFamily.SERIAL, 2)


def test_un_indice_rare_pese_plus_qu_un_indice_repandu():
    assert _FREQUENCIES.weight((ClueFamily.SERIAL, 2)) > _FREQUENCIES.weight((ClueFamily.SERIAL, 1))


def test_le_poids_d_une_arete_somme_les_indices_partages():
    publications = [
        _publication(1, _LAB, _RARE_SERIAL),
        _publication(2, _LAB, _RARE_SERIAL),
        _publication(3),
    ]

    weights = edge_weights(publications, _FREQUENCIES)

    assert weights == {(0, 1): _FREQUENCIES.weight(_LAB) + _FREQUENCIES.weight(_RARE_SERIAL)}


def _person(*, isolated_anchored=False, bridge=False):
    """Six publications : trois du laboratoire, ancrées, puis trois d'une revue rare."""
    main = [_publication(i, _LAB, anchored=True) for i in (1, 2, 3)]
    other = [
        _publication(4, _RARE_SERIAL, *((_LAB,) if bridge else ()), anchored=isolated_anchored)
    ]
    other += [_publication(i, _RARE_SERIAL) for i in (5, 6)]
    return main + other


def test_un_cluster_isole_hors_du_cluster_principal_est_signale():
    assert signaled_clusters(_person(), _FREQUENCIES, _labels(0, 0, 0, 1, 1, 1)) == [[4, 5, 6]]


def test_un_cluster_qui_contient_une_contribution_ancree_n_est_pas_signale():
    publications = _person(isolated_anchored=True)

    assert signaled_clusters(publications, _FREQUENCIES, _labels(0, 0, 0, 1, 1, 1)) == []


def test_un_cluster_fortement_relie_au_reste_n_est_pas_signale():
    publications = _person(bridge=True)

    assert signaled_clusters(publications, _FREQUENCIES, _labels(0, 0, 0, 1, 1, 1)) == []


def test_le_cluster_principal_reunit_le_plus_de_contributions_ancrees():
    """Le cluster le plus grand n'est pas principal s'il est sans ancrage."""
    publications = [_publication(1, _LAB, anchored=True)] + [
        _publication(i, _RARE_SERIAL) for i in range(2, 8)
    ]

    clusters = signaled_clusters(publications, _FREQUENCIES, _labels(0, 1, 1, 1, 1, 1, 1))

    assert clusters == [[2, 3, 4, 5, 6, 7]]


def test_un_petit_cluster_n_est_pas_signale():
    publications = _person()

    assert signaled_clusters(publications, _FREQUENCIES, _labels(0, 0, 0, 0, 1, 1)) == []


def test_une_personne_a_peu_de_publications_n_est_pas_examinee():
    assert signaled_clusters(_person()[:5], _FREQUENCIES, _labels(0, 0, 0, 1, 1)) == []


def _context(publication_id, *, persons=(), laboratories=(), year=None):
    return ContributionContext(
        publication_id, frozenset(persons), frozenset(laboratories), frozenset(), None, year
    )


def test_une_publication_proche_des_publications_rejetees_leur_ressemble():
    own = [_context(1, persons={10}), _context(2, persons={11})]
    rejected = [_context(3, persons={20}), _context(4, persons={21})]

    assert resembles_rejected(99, _context(5, persons={20}), own, rejected)
    assert not resembles_rejected(99, _context(6, persons={10}), own, rejected)


def test_une_publication_sans_indice_decisif_ne_ressemble_pas_aux_publications_rejetees():
    own = [_context(1, persons={10})]
    rejected = [_context(2, persons={20})]

    assert not resembles_rejected(99, _context(3, persons={30}), own, rejected)
