"""Tests de l'assemblage des arêtes des signaux #2 (clés partagées) et #3 (rapprochement par titre)."""

from application.pipeline.relations.phase import (
    _build_shared_key_edges,
    _build_title_match_edges,
)
from application.ports.pipeline.relations import SharedKeyPair, TitleMatch
from domain.publications.relations import RelationType


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


class TestBuildTitleMatchEdges:
    def test_directed_edge_targets_parent_publication(self):
        edges = _build_title_match_edges(
            [TitleMatch(child_id=5, parent_id=9, parent_doi="10.1234/parent")],
            RelationType.IS_CORRECTION_OF,
        )
        assert len(edges) == 1
        e = edges[0]
        assert e.from_publication_id == 5
        assert e.relation_type == "is_correction_of"
        assert e.target_publication_id == 9
        assert e.target_doi == "10.1234/parent"
        assert e.source == "title_match"

    def test_preprint_type_and_doiless_parent(self):
        # Parent au corpus sans DOI : la cible est désignée par publication_id, target_doi reste None.
        edges = _build_title_match_edges(
            [TitleMatch(child_id=7, parent_id=3, parent_doi=None)],
            RelationType.IS_PREPRINT_OF,
        )
        assert len(edges) == 1
        e = edges[0]
        assert e.relation_type == "is_preprint_of"
        assert e.target_publication_id == 3
        assert e.target_doi is None
