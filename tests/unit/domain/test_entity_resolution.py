"""Composantes connexes des enregistrements sources reliés par des clés partagées (`domain.entity_resolution.connected_components`).

Les composantes sont transitives et triées ; deux clés de types différents restent distinctes ; un enregistrement source sans clé forme sa propre composante.
"""

from __future__ import annotations

from domain.entity_resolution import connected_components


def _tok(*pairs: tuple[str, str]) -> frozenset[tuple[str, str]]:
    return frozenset(pairs)


class TestConnectedComponents:
    def test_empty(self):
        assert connected_components([]) == []

    def test_singletons_without_tokens(self):
        """Chaque enregistrement source sans clé forme sa propre composante."""
        assert connected_components([(3, _tok()), (1, _tok()), (2, _tok())]) == [[1], [2], [3]]

    def test_shared_doi_groups(self):
        result = connected_components([(1, _tok(("doi", "10.1/x"))), (2, _tok(("doi", "10.1/x")))])
        assert result == [[1, 2]]

    def test_transitive_closure_across_keys(self):
        """1 et 2 partagent un DOI, 2 et 3 un identifiant HAL : 1, 2 et 3 forment une seule composante."""
        result = connected_components(
            [
                (1, _tok(("doi", "10.1/x"))),
                (2, _tok(("doi", "10.1/x"), ("hal_id", "hal-1"))),
                (3, _tok(("hal_id", "hal-1"))),
            ]
        )
        assert result == [[1, 2, 3]]

    def test_distinct_token_types_do_not_bridge(self):
        """Un DOI `x` et un NNT `x` sont deux clés distinctes."""
        result = connected_components([(1, _tok(("doi", "x"))), (2, _tok(("nnt", "x")))])
        assert result == [[1], [2]]

    def test_two_disjoint_groups(self):
        result = connected_components(
            [
                (1, _tok(("doi", "a"))),
                (2, _tok(("doi", "a"))),
                (10, _tok(("nnt", "b"))),
                (11, _tok(("nnt", "b"))),
            ]
        )
        assert result == [[1, 2], [10, 11]]

    def test_deterministic_order_independent(self):
        """Le résultat est indépendant de l'ordre d'entrée."""
        members = [
            (5, _tok(("hal_id", "h"))),
            (2, _tok(("doi", "d"), ("hal_id", "h"))),
            (9, _tok(("pmid", "p"))),
            (4, _tok(("doi", "d"))),
        ]
        expected = [[2, 4, 5], [9]]
        assert connected_components(members) == expected
        assert connected_components(list(reversed(members))) == expected

    def test_root_discovered_late_is_reached_through_a_chain(self):
        """3 rejoint 2, puis 2 rejoint 1 : 3 atteint la racine 1 en deux sauts."""
        result = connected_components(
            [
                (2, _tok(("doi", "x"))),
                (3, _tok(("doi", "x"))),
                (1, _tok(("nnt", "y"), ("doi", "x"))),
            ]
        )
        assert result == [[1, 2, 3]]

    def test_multivalued_hal_ids_bridge_two_records(self):
        """Un enregistrement source à deux identifiants HAL relie deux enregistrements sources qui en partagent chacun un seul."""
        result = connected_components(
            [
                (1, _tok(("hal_id", "hal-1"))),
                (2, _tok(("hal_id", "hal-1"), ("hal_id", "hal-2"))),
                (3, _tok(("hal_id", "hal-2"))),
            ]
        )
        assert result == [[1, 2, 3]]
