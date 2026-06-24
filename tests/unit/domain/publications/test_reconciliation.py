"""Tests purs de `plan_reconciliation` : assignation SP → pub-ancre (match/create/skip + merge/split unifiés).

`pub_id=None` = SP orpheline (pas encore matérialisée). La matrice match/create/skip est dans `TestAssignmentOfOrphans`.
"""

from domain.publications.reconciliation import (
    DissolvedPublication,
    ReconcileMember,
    WorkGroup,
    plan_reconciliation,
)


def _m(sp_id, pub_id, *, pub_doi=None, doi=None, tokens=(), in_perimeter=False, tn="t", year=2024):
    return ReconcileMember(
        source_publication_id=sp_id,
        publication_id=pub_id,
        publication_doi=pub_doi,
        effective_doi=doi,
        tokens=frozenset(tokens),
        in_perimeter=in_perimeter,
        title_normalized=tn,
        pub_year=year,
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


class TestAssignmentOfOrphans:
    """Matrice match / create / skip : les orphelins (`pub_id=None`) traités par le même primitif."""

    def test_match_orphan_joins_existing_pub(self):
        """Orphelin + pub existante portant le même DOI → l'orphelin rejoint la pub (match)."""
        plan = plan_reconciliation(
            [
                _m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(2, 50, pub_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]),
            ]
        )
        assert _groups(plan) == {50: (1, 2)}
        assert plan.dissolved == ()

    def test_create_orphans_with_perimeter(self):
        """Orphelins seuls, ≥1 in-périmètre, aucune pub → on crée une pub (target=None)."""
        plan = plan_reconciliation(
            [
                _m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")], in_perimeter=True),
                _m(
                    2, None, doi="10.1/x", tokens=[("doi", "10.1/x")]
                ),  # hors-périmètre, mais voisin in
            ]
        )
        assert _groups(plan) == {None: (1, 2)}
        assert plan.dissolved == ()

    def test_skip_orphans_out_of_perimeter(self):
        """Orphelins seuls, aucun in-périmètre → aucun groupe (ils restent orphelins)."""
        plan = plan_reconciliation(
            [
                _m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(2, None, doi="10.1/x", tokens=[("doi", "10.1/x")]),
            ]
        )
        assert plan.groups == ()
        assert plan.dissolved == ()

    def test_lone_orphan_in_perimeter_creates(self):
        plan = plan_reconciliation(
            [_m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")], in_perimeter=True)]
        )
        assert _groups(plan) == {None: (1,)}

    def test_lone_orphan_out_of_perimeter_skipped(self):
        plan = plan_reconciliation([_m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")])])
        assert plan.groups == ()

    def test_create_gated_by_missing_metadata(self):
        """Orphelin in-périmètre mais sans titre/année → pas de create (skip), comme le gate
        `has_minimal_publication_metadata` (sinon `pub_year NOT NULL` ferait échouer la création)."""
        plan = plan_reconciliation(
            [
                _m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")], in_perimeter=True, year=None),
                _m(2, None, doi="10.1/x", tokens=[("doi", "10.1/x")], in_perimeter=True, tn=""),
            ]
        )
        assert plan.groups == ()  # aucun membre matérialisable

    def test_mixed_orphan_matches_other_orphan_skipped(self):
        """Un orphelin rejoint une pub (DOI X) ; un autre orphelin (DOI Y, hors-périmètre) skip."""
        plan = plan_reconciliation(
            [
                _m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(2, 50, pub_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(3, None, doi="10.2/y", tokens=[("doi", "10.2/y")]),
            ]
        )
        assert _groups(plan) == {50: (1, 2)}  # sp3 (DOI Y, hors-périmètre) non groupé
        assert plan.dissolved == ()


class TestExternalDoiCarrier:
    """Porteur du DOI hors voisinage : une publication existante porte le DOI sans qu'aucune SP
    du voisinage n'y soit rattachée (orpheline après TRUNCATE+réimport, ou dérive). Le groupe s'y
    ancre au lieu de créer une pub neuve qui heurterait la contrainte unique sur le DOI."""

    def test_orphan_partition_anchors_to_external_carrier(self):
        plan = plan_reconciliation(
            [
                _m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")], in_perimeter=True),
                _m(2, None, doi="10.1/x", tokens=[("doi", "10.1/x")]),
            ],
            existing_pub_by_doi={"10.1/x": 132},
        )
        assert _groups(plan) == {132: (1, 2)}
        assert plan.dissolved == ()

    def test_no_external_carrier_still_creates(self):
        """Sans porteur connu, comportement inchangé : création (target=None)."""
        plan = plan_reconciliation(
            [_m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")], in_perimeter=True)],
            existing_pub_by_doi={},
        )
        assert _groups(plan) == {None: (1,)}

    def test_materialized_without_carrier_prefers_external_carrier(self):
        """SP matérialisée sur une pub qui ne porte pas le DOI (dérive) → ancre = porteur externe,
        la pub dérivée est dissoute vers lui."""
        plan = plan_reconciliation(
            [_m(1, 50, doi="10.1/x", tokens=[("doi", "10.1/x")])],  # pub 50 ne porte pas X
            existing_pub_by_doi={"10.1/x": 90},
        )
        assert _groups(plan) == {90: (1,)}
        assert plan.dissolved == (DissolvedPublication(50, 90),)


class TestWorkGroupShape:
    def test_group_sp_ids_sorted(self):
        plan = plan_reconciliation(
            [
                _m(7, 10, doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(2, 10, doi="10.1/x", tokens=[("doi", "10.1/x")]),
            ]
        )
        assert plan.groups == (WorkGroup(10, (2, 7)),)
