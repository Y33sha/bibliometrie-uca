"""Tests de l'assemblage des arêtes du signal #2 (clés de confirmation partagées)."""

from application.pipeline.relations.populate_relations import _build_shared_key_edges
from application.ports.pipeline.relations import SharedKeyPair


def _pair(a_id, a_dt, b_id, b_dt):
    return SharedKeyPair(a_id, a_dt, f"10.1/{a_id}", b_id, b_dt, f"10.1/{b_id}")


class TestBuildSharedKeyEdges:
    def test_preprint_pair_directed(self):
        edges = _build_shared_key_edges(
            [_pair(10, "article", 20, "preprint")], declared_pairs=set()
        )
        assert len(edges) == 1
        assert edges[0].from_publication_id == 20  # le preprint est sujet
        assert edges[0].relation_type == "is_preprint_of"
        assert edges[0].target_doi == "10.1/10"

    def test_unexpected_couple_is_related_to(self):
        edges = _build_shared_key_edges([_pair(30, "article", 40, "article")], declared_pairs=set())
        assert [(e.from_publication_id, e.relation_type) for e in edges] == [(30, "is_related_to")]

    def test_is_related_to_suppressed_when_pair_already_declared(self):
        # La paire {30, 40} porte déjà une relation précise (signal #1) → pas de is_related_to.
        edges = _build_shared_key_edges(
            [_pair(30, "article", 40, "article")], declared_pairs={frozenset((30, 40))}
        )
        assert edges == []

    def test_precise_relation_kept_even_if_declared(self):
        # Une relation précise du signal #2 n'est pas écartée par une paire déclarée.
        edges = _build_shared_key_edges(
            [_pair(10, "article", 20, "preprint")], declared_pairs={frozenset((10, 20))}
        )
        assert len(edges) == 1
        assert edges[0].relation_type == "is_preprint_of"

    def test_peer_review_skipped(self):
        edges = _build_shared_key_edges(
            [_pair(50, "peer_review", 60, "article")], declared_pairs=set()
        )
        assert edges == []
