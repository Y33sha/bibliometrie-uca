"""Tests purs de `plan_reconciliation` : assignation SP → pub-ancre (merge + split unifiés)."""

from domain.publications.reconciliation import (
    DissolvedPublication,
    ReconcileMember,
    WorkGroup,
    plan_reconciliation,
)


def _m(sp_id, pub_id, *, pub_doi=None, doi=None, tokens=()):
    return ReconcileMember(
        source_publication_id=sp_id,
        publication_id=pub_id,
        publication_doi=pub_doi,
        effective_doi=doi,
        tokens=frozenset(tokens),
    )


def _groups(plan):
    return {g.target_publication_id: g.source_publication_ids for g in plan.groups}


class TestMerge:
    def test_two_pubs_same_doi_merge_to_carrier(self):
        """Deux pubs portant le même DOI, SP reliées par le token DOI → fusion vers le min des porteurs."""
        plan = plan_reconciliation(
            [
                _m(1, 10, pub_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(2, 20, pub_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]),
            ]
        )
        assert _groups(plan) == {10: (1, 2)}
        assert plan.dissolved == (DissolvedPublication(20, 10),)

    def test_no_doi_component_merges_by_min_sp(self):
        """Composante sans DOI (reliée par hal_id), deux pubs → ancre = pub du plus petit SP."""
        plan = plan_reconciliation(
            [
                _m(5, 50, tokens=[("hal_id", "hal-1")]),
                _m(3, 30, tokens=[("hal_id", "hal-1")]),
            ]
        )
        assert _groups(plan) == {30: (3, 5)}  # min SP = 3 → pub 30
        assert plan.dissolved == (DissolvedPublication(50, 30),)

    def test_single_pub_stable(self):
        """Une seule pub, rien à faire : un groupe sur elle-même, aucune dissolution."""
        plan = plan_reconciliation(
            [
                _m(1, 10, pub_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(2, 10, pub_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]),
            ]
        )
        assert _groups(plan) == {10: (1, 2)}
        assert plan.dissolved == ()


class TestDoiAnchor:
    def test_doi_carrier_beats_smaller_min_sp(self):
        """L'ancre est le pub qui PORTE le DOI, même si un autre pub a un plus petit SP."""
        plan = plan_reconciliation(
            [
                _m(1, 50, doi="10.1/x", tokens=[("doi", "10.1/x")]),  # pub 50 ne porte pas X
                _m(9, 90, pub_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]),  # porteur
            ]
        )
        # min SP = 1 (pub 50), mais l'ancre est 90 (porteur du DOI).
        assert _groups(plan) == {90: (1, 9)}
        assert plan.dissolved == (DissolvedPublication(50, 90),)


class TestSplit:
    def test_pub_with_two_dois_splits(self):
        """Une pub portant doi=X héberge une SP doi=Y (reliées par hal_id) → X garde la pub, Y → nouveau pub."""
        plan = plan_reconciliation(
            [
                _m(
                    1,
                    10,
                    pub_doi="10.1/x",
                    doi="10.1/x",
                    tokens=[("hal_id", "h"), ("doi", "10.1/x")],
                ),
                _m(
                    2,
                    10,
                    pub_doi="10.1/x",
                    doi="10.2/y",
                    tokens=[("hal_id", "h"), ("doi", "10.2/y")],
                ),
            ]
        )
        assert _groups(plan) == {10: (1,), None: (2,)}  # X garde pub 10, Y → nouveau pub
        assert plan.dissolved == ()  # pub 10 survit (ancre de X)

    def test_residual_no_doi_sp_stays(self):
        """Composante multi-DOI : la SP sans DOI est résiduelle, laissée sur son pub, non dissoute."""
        plan = plan_reconciliation(
            [
                _m(
                    1,
                    10,
                    pub_doi="10.1/x",
                    doi="10.1/x",
                    tokens=[("hal_id", "h"), ("doi", "10.1/x")],
                ),
                _m(
                    2,
                    20,
                    pub_doi="10.2/y",
                    doi="10.2/y",
                    tokens=[("hal_id", "h"), ("doi", "10.2/y")],
                ),
                _m(3, 30, tokens=[("hal_id", "h")]),  # sans DOI → résiduelle
            ]
        )
        assert _groups(plan) == {10: (1,), 20: (2,)}
        # pub 30 retient la SP résiduelle 3 → pas dissoute.
        assert plan.dissolved == ()


class TestWorkGroupShape:
    def test_group_sp_ids_sorted(self):
        plan = plan_reconciliation(
            [
                _m(7, 10, doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(2, 10, doi="10.1/x", tokens=[("doi", "10.1/x")]),
            ]
        )
        assert plan.groups == (WorkGroup(10, (2, 7)),)
