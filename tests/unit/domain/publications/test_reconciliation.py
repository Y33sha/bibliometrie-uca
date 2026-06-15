"""Tests purs de `domain.publications.reconciliation.plan_merges`.

Garde : fusion par composante, ancre `min(source_publication_id)`, cannot-link DOI (≥2 DOI = fusion conservatrice par DOI, résidu sans-DOI laissé), et détection des publications étalées sur plusieurs composantes (split différé).
"""

from domain.publications.reconciliation import MergeGroup, ReconcileMember, plan_merges


def _m(sp, pub, doi=None, tokens=()) -> ReconcileMember:
    return ReconcileMember(sp, pub, doi, frozenset(tokens))


class TestMerge:
    def test_two_pubs_sharing_doi_merge(self):
        plan = plan_merges(
            [
                _m(1, 10, "x", [("doi", "x")]),
                _m(2, 20, "x", [("doi", "x")]),
            ]
        )
        assert plan.merges == (MergeGroup(10, (20,)),)
        assert plan.deferred_split_publication_ids == ()

    def test_no_doi_shared_secondary_key_merge(self):
        """Deux publications sans DOI partageant un hal_id : une œuvre, fusion."""
        plan = plan_merges(
            [
                _m(1, 10, None, [("hal_id", "h")]),
                _m(2, 20, None, [("hal_id", "h")]),
            ]
        )
        assert plan.merges == (MergeGroup(10, (20,)),)

    def test_same_publication_no_merge(self):
        plan = plan_merges(
            [
                _m(1, 10, "x", [("doi", "x")]),
                _m(2, 10, "x", [("doi", "x")]),
            ]
        )
        assert plan.merges == ()

    def test_anchor_is_min_source_publication_id(self):
        """L'ancre est la publication de la SP au plus petit id, pas la plus petite publication."""
        plan = plan_merges(
            [
                _m(5, 10, None, [("nnt", "a")]),
                _m(2, 20, None, [("nnt", "a")]),
            ]
        )
        assert plan.merges == (MergeGroup(20, (10,)),)

    def test_three_pubs_same_doi_single_group(self):
        plan = plan_merges(
            [
                _m(1, 10, "x", [("doi", "x")]),
                _m(2, 20, "x", [("doi", "x")]),
                _m(3, 30, "x", [("doi", "x")]),
            ]
        )
        assert plan.merges == (MergeGroup(10, (20, 30)),)

    def test_disjoint_components_no_merge(self):
        plan = plan_merges(
            [
                _m(1, 10, "x", [("doi", "x")]),
                _m(2, 20, "y", [("doi", "y")]),
            ]
        )
        assert plan.merges == ()
        assert plan.deferred_split_publication_ids == ()


class TestDoiCannotLink:
    def test_distinct_dois_bridged_by_secondary_not_merged(self):
        """hal_id partagé par-dessus deux DOI distincts : conflation, pas de fusion inter-DOI."""
        plan = plan_merges(
            [
                _m(1, 10, "x", [("doi", "x"), ("hal_id", "h")]),
                _m(2, 20, "y", [("doi", "y"), ("hal_id", "h")]),
            ]
        )
        assert plan.merges == ()

    def test_no_doi_bridge_residue_left_intact(self):
        """Une SP sans DOI pontant deux DOI distincts : sa publication reste intacte (résidu)."""
        plan = plan_merges(
            [
                _m(1, 10, "x", [("doi", "x"), ("hal_id", "h")]),
                _m(2, 20, "y", [("doi", "y"), ("hal_id", "h")]),
                _m(3, 30, None, [("hal_id", "h")]),
            ]
        )
        assert plan.merges == ()
        assert plan.deferred_split_publication_ids == ()

    def test_same_doi_merge_within_multi_doi_component(self):
        """Composante à 2 DOI : les publications d'un même DOI fusionnent, l'autre DOI reste."""
        plan = plan_merges(
            [
                _m(1, 10, "x", [("doi", "x"), ("hal_id", "h")]),
                _m(2, 20, "x", [("doi", "x")]),
                _m(3, 30, "y", [("doi", "y"), ("hal_id", "h")]),
            ]
        )
        # x : pub 10 + pub 20 → fusion ; y : pub 30 seul → rien.
        assert plan.merges == (MergeGroup(10, (20,)),)


class TestDeferredSplit:
    def test_publication_spanning_components_deferred(self):
        """Pub 10 a deux SP non co-connexes (clé retirée) : split en attente, exclue du merge."""
        plan = plan_merges(
            [
                _m(1, 10, None, [("nnt", "a")]),
                _m(2, 10, None, [("pmid", "b")]),
                _m(3, 20, None, [("nnt", "a")]),
                _m(4, 30, None, [("pmid", "b")]),
            ]
        )
        # Sans la garde, pub 10 serait absorbée dans deux groupes (fusion de travers).
        assert plan.merges == ()
        assert plan.deferred_split_publication_ids == (10,)
