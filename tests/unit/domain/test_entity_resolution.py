"""Tests unitaires de `domain.entity_resolution.connected_components`.

Garde le contrat du clustering ER : fermeture transitive sur clés partagées, isolation par type de clé, singletons sans clé, et déterminisme (composantes triées, racine au `min`).
"""

from __future__ import annotations

from domain.entity_resolution import connected_components


def _tok(*pairs: tuple[str, str]) -> frozenset[tuple[str, str]]:
    return frozenset(pairs)


class TestConnectedComponents:
    def test_empty(self):
        assert connected_components([]) == []

    def test_singletons_without_tokens(self):
        """Des SP sans clé ne s'apparentent à rien : une composante chacune."""
        assert connected_components([(3, _tok()), (1, _tok()), (2, _tok())]) == [[1], [2], [3]]

    def test_shared_doi_groups(self):
        result = connected_components([(1, _tok(("doi", "10.1/x"))), (2, _tok(("doi", "10.1/x")))])
        assert result == [[1, 2]]

    def test_transitive_closure_across_keys(self):
        """1↔2 par DOI, 2↔3 par HAL : 1-2-3 forment une seule composante (transitivité)."""
        result = connected_components(
            [
                (1, _tok(("doi", "10.1/x"))),
                (2, _tok(("doi", "10.1/x"), ("hal_id", "hal-1"))),
                (3, _tok(("hal_id", "hal-1"))),
            ]
        )
        assert result == [[1, 2, 3]]

    def test_distinct_token_types_do_not_bridge(self):
        """Un DOI `x` et un NNT `x` ne relient pas (tokens namespacés par type)."""
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
        """L'ordre d'entrée n'influe pas sur le résultat (confluent)."""
        members = [
            (5, _tok(("hal_id", "h"))),
            (2, _tok(("doi", "d"), ("hal_id", "h"))),
            (9, _tok(("pmid", "p"))),
            (4, _tok(("doi", "d"))),
        ]
        expected = [[2, 4, 5], [9]]
        assert connected_components(members) == expected
        assert connected_components(list(reversed(members))) == expected

    def test_multivalued_hal_ids_bridge_two_records(self):
        """Une SP portant deux HAL ids ponte deux SP qui n'en partagent qu'un chacune."""
        result = connected_components(
            [
                (1, _tok(("hal_id", "hal-1"))),
                (2, _tok(("hal_id", "hal-1"), ("hal_id", "hal-2"))),
                (3, _tok(("hal_id", "hal-2"))),
            ]
        )
        assert result == [[1, 2, 3]]
