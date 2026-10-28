"""Tests purs de `plan_reconciliation` : assignation enregistrement source → publication ancre (match/create/skip + merge/split unifiés).

`publication_id=None` = enregistrement source orpheline (pas encore matérialisée). La matrice match/create/skip est dans `TestAssignmentOfOrphans`.
"""

from domain.publications.reconciliation import (
    DissolvedPublication,
    ReconcileMember,
    WorkGroup,
    plan_reconciliation,
)


def _m(
    source_record_id,
    publication_id,
    *,
    publication_doi=None,
    doi=None,
    tokens=(),
    in_perimeter=False,
    tn="t",
    year=2024,
    doc_type=None,
):
    return ReconcileMember(
        source_record_id=source_record_id,
        publication_id=publication_id,
        publication_doi=publication_doi,
        effective_doi=doi,
        tokens=frozenset(tokens),
        in_perimeter=in_perimeter,
        title_normalized=tn,
        publication_year=year,
        doc_type=doc_type,
    )


def _groups(plan):
    return {g.target_publication_id: g.source_record_ids for g in plan.groups}


class TestMerge:
    def test_two_publications_same_doi_merge_to_carrier(self):
        """Deux publications qui ont le même DOI, enregistrement source relié par le token DOI → fusion vers le min des porteurs."""
        plan = plan_reconciliation(
            [
                _m(1, 10, publication_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(2, 20, publication_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]),
            ]
        )
        assert _groups(plan) == {10: (1, 2)}
        assert plan.dissolved == (DissolvedPublication(20, 10),)

    def test_publication_with_sources_outside_neighborhood_is_not_dissolved(self):
        """Seul un enregistrement source de la publication 20 est dans le voisinage : la publication garde ses autres enregistrements sources, elle n'est pas dissoute."""
        plan = plan_reconciliation(
            [
                _m(1, 10, tokens=[("hal_id", "hal-1")]),
                _m(2, 20, tokens=[("hal_id", "hal-1")]),
            ],
            publication_sizes={10: 1, 20: 3},
        )
        assert _groups(plan) == {10: (1, 2)}
        assert plan.dissolved == ()

    def test_no_doi_component_merges_by_min_source_record(self):
        """Composante sans DOI (reliée par hal_id), deux publications → ancre = publication du plus petit enregistrement source."""
        plan = plan_reconciliation(
            [
                _m(5, 50, tokens=[("hal_id", "hal-1")]),
                _m(3, 30, tokens=[("hal_id", "hal-1")]),
            ]
        )
        assert _groups(plan) == {30: (3, 5)}  # min enregistrement source = 3 → publication 30
        assert plan.dissolved == (DissolvedPublication(50, 30),)

    def test_single_publication_stable(self):
        """Une seule publication, rien à faire : un groupe sur elle-même, aucune dissolution."""
        plan = plan_reconciliation(
            [
                _m(1, 10, publication_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(2, 10, publication_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]),
            ]
        )
        assert _groups(plan) == {10: (1, 2)}
        assert plan.dissolved == ()


class TestDoiAnchor:
    def test_doi_carrier_beats_smaller_min_source_record(self):
        """L'ancre est la publication qui A le DOI, même si une autre publication a un plus petit enregistrement source."""
        plan = plan_reconciliation(
            [
                _m(1, 50, doi="10.1/x", tokens=[("doi", "10.1/x")]),  # publication 50 n'a pas X
                _m(
                    9, 90, publication_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]
                ),  # porteur
            ]
        )
        # min enregistrement source = 1 (publication 50), mais l'ancre est 90 (porteur du DOI).
        assert _groups(plan) == {90: (1, 9)}
        assert plan.dissolved == (DissolvedPublication(50, 90),)


class TestSplit:
    def test_publication_with_two_dois_splits(self):
        """Une publication qui a doi=X héberge un enregistrement source doi=Y (reliées par hal_id) → X garde la publication, Y → nouveau publication."""
        plan = plan_reconciliation(
            [
                _m(
                    1,
                    10,
                    publication_doi="10.1/x",
                    doi="10.1/x",
                    tokens=[("hal_id", "h"), ("doi", "10.1/x")],
                ),
                _m(
                    2,
                    10,
                    publication_doi="10.1/x",
                    doi="10.2/y",
                    tokens=[("hal_id", "h"), ("doi", "10.2/y")],
                ),
            ]
        )
        assert _groups(plan) == {
            10: (1,),
            None: (2,),
        }  # X garde la publication 10, Y → nouvelle publication
        assert plan.dissolved == ()  # publication 10 survit (ancre de X)

    def test_residual_no_doi_source_record_stays(self):
        """Composante multi-DOI : l'enregistrement source sans DOI est résiduelle, laissée sur son publication, non dissoute."""
        plan = plan_reconciliation(
            [
                _m(
                    1,
                    10,
                    publication_doi="10.1/x",
                    doi="10.1/x",
                    tokens=[("hal_id", "h"), ("doi", "10.1/x")],
                ),
                _m(
                    2,
                    20,
                    publication_doi="10.2/y",
                    doi="10.2/y",
                    tokens=[("hal_id", "h"), ("doi", "10.2/y")],
                ),
                _m(3, 30, tokens=[("hal_id", "h")]),  # sans DOI → résiduelle
            ]
        )
        assert _groups(plan) == {10: (1,), 20: (2,)}
        # publication 30 retient l'enregistrement source résiduelle 3 → pas dissoute.
        assert plan.dissolved == ()


class TestDetachment:
    def test_enregistrement_source_sans_cle_ni_annee_est_detache(self):
        """Régression : un enregistrement source OpenAlex renvoyé sans DOI ni année perd toutes ses clés ; il ne peut fonder aucune publication et devient orphelin."""
        plan = plan_reconciliation(
            [
                _m(1, 10, publication_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(2, 10, publication_doi="10.1/x", tokens=(), year=None),
            ]
        )
        assert _groups(plan) == {10: (1,)}
        assert plan.detached == (2,)
        assert plan.dissolved == ()

    def test_enregistrement_source_sans_cle_avec_annee_fonde_une_publication(self):
        plan = plan_reconciliation(
            [
                _m(1, 10, publication_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(2, 10, publication_doi="10.1/x", tokens=()),
            ]
        )
        assert _groups(plan) == {10: (1,), None: (2,)}
        assert plan.detached == ()


class TestExclusion:
    """Enregistrements sources écartés (`is_excluded_source_record`) : hors de toute partition, détachés s'ils sont matérialisés."""

    def test_excluded_record_is_detached_from_its_publication(self):
        plan = plan_reconciliation(
            [
                _m(1, 10, publication_doi="10.1/x", doi="10.1/x", tokens=[("hal_id", "hal-1")]),
                _m(2, 10, tn="list of contributors", tokens=[("hal_id", "hal-1")]),
            ]
        )
        assert _groups(plan) == {10: (1,)}
        assert plan.detached == (2,)
        assert plan.dissolved == ()

    def test_publication_of_excluded_records_only_is_not_dissolved(self):
        """Régression : une publication faite de copies GRESIS perd tous ses enregistrements sources, sans successeur. Le recalcul la supprime."""
        gresis = "10.60692/m2raz-tjw54"
        plan = plan_reconciliation(
            [
                _m(1, 10, publication_doi=gresis, doi=gresis, tokens=[("doi", gresis)]),
                _m(2, 10, publication_doi=gresis, doi=gresis, tokens=[("doi", gresis)]),
            ],
            publication_sizes={10: 2},
        )
        assert plan.groups == ()
        assert plan.detached == (1, 2)
        assert plan.dissolved == ()

    def test_excluded_orphan_founds_nothing(self):
        plan = plan_reconciliation([_m(1, None, tn="front matter", in_perimeter=True)])
        assert plan.groups == ()
        assert plan.detached == ()

    def test_excluded_record_does_not_bridge_two_works(self):
        """Un enregistrement source écarté partage une clé avec deux œuvres. Les deux œuvres restent distinctes."""
        plan = plan_reconciliation(
            [
                _m(1, 10, tokens=[("hal_id", "hal-1")]),
                _m(2, 20, tokens=[("pmid", "42")]),
                _m(3, 10, tn="index", tokens=[("hal_id", "hal-1"), ("pmid", "42")]),
            ]
        )
        assert _groups(plan) == {10: (1,), 20: (2,)}
        assert plan.detached == (3,)
        assert plan.dissolved == ()

    def test_merged_publication_with_excluded_record_dissolves_into_successor(self):
        """La publication 20 cède un enregistrement source à 10, et son plus petit enregistrement source est écarté. Elle est dissoute vers 10."""
        plan = plan_reconciliation(
            [
                _m(1, 20, tn="index", tokens=()),
                _m(2, 10, tokens=[("hal_id", "hal-1")]),
                _m(3, 20, tokens=[("hal_id", "hal-1")]),
            ]
        )
        assert _groups(plan) == {10: (2, 3)}
        assert plan.detached == (1,)
        assert plan.dissolved == (DissolvedPublication(20, 10),)


class TestAssignmentOfOrphans:
    """Matrice match / create / skip : les orphelins (`publication_id=None`) traités par le même primitif."""

    def test_match_orphan_joins_existing_publication(self):
        """Orphelin + publication existante qui a le même DOI → l'orphelin rejoint la publication (match)."""
        plan = plan_reconciliation(
            [
                _m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(2, 50, publication_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]),
            ]
        )
        assert _groups(plan) == {50: (1, 2)}
        assert plan.dissolved == ()

    def test_create_orphans_with_perimeter(self):
        """Orphelins seuls, ≥1 in-périmètre, aucune publication → on crée une publication (target=None)."""
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

    def test_no_member_able_to_found_a_publication_skipped(self):
        """Aucun enregistrement ne fonde de publication : l'un est d'un type non admissible, l'autre est hors périmètre."""
        key = [("hal_id", "dumas-01234567")]
        plan = plan_reconciliation(
            [
                _m(1, None, tokens=key, in_perimeter=True, doc_type="memoir"),
                _m(2, None, tokens=key, in_perimeter=False, doc_type="article"),
            ]
        )
        assert plan.groups == ()

    def test_one_member_able_to_found_a_publication_creates(self):
        """Un enregistrement in-périmètre d'un type du périmètre métier suffit ; l'arbitrage du type revient au recalcul des métadonnées."""
        key = [("hal_id", "dumas-01234567")]
        plan = plan_reconciliation(
            [
                _m(1, None, tokens=key, in_perimeter=True, doc_type="memoir"),
                _m(2, None, tokens=key, in_perimeter=True, doc_type="article"),
            ]
        )
        assert len(plan.groups) == 1

    def test_untyped_member_in_perimeter_creates(self):
        plan = plan_reconciliation(
            [_m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")], in_perimeter=True)]
        )
        assert len(plan.groups) == 1

    def test_create_gated_by_missing_metadata(self):
        """Orphelin in-périmètre mais sans titre/année → pas de create (skip), comme le gate
        `has_minimal_publication_metadata` (sinon `publication_year NOT NULL` ferait échouer la création)."""
        plan = plan_reconciliation(
            [
                _m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")], in_perimeter=True, year=None),
                _m(2, None, doi="10.1/x", tokens=[("doi", "10.1/x")], in_perimeter=True, tn=""),
            ]
        )
        assert plan.groups == ()  # aucun membre matérialisable

    def test_mixed_orphan_matches_other_orphan_skipped(self):
        """Un orphelin rejoint une publication (DOI X) ; un autre orphelin (DOI Y, hors-périmètre) skip."""
        plan = plan_reconciliation(
            [
                _m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(2, 50, publication_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(3, None, doi="10.2/y", tokens=[("doi", "10.2/y")]),
            ]
        )
        assert _groups(plan) == {50: (1, 2)}  # sp3 (DOI Y, hors-périmètre) non groupé
        assert plan.dissolved == ()


class TestExternalDoiCarrier:
    """Porteur du DOI hors voisinage : une publication existante a le DOI sans qu'aucun enregistrement source
    du voisinage n'y soit rattachée (orpheline après TRUNCATE+réimport, ou dérive). Le groupe s'y
    ancre au lieu de créer une publication neuve qui heurterait la contrainte unique sur le DOI."""

    def test_orphan_partition_anchors_to_external_carrier(self):
        plan = plan_reconciliation(
            [
                _m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")], in_perimeter=True),
                _m(2, None, doi="10.1/x", tokens=[("doi", "10.1/x")]),
            ],
            existing_publication_by_doi={"10.1/x": 132},
        )
        assert _groups(plan) == {132: (1, 2)}
        assert plan.dissolved == ()

    def test_no_external_carrier_still_creates(self):
        """Sans porteur connu, comportement inchangé : création (target=None)."""
        plan = plan_reconciliation(
            [_m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")], in_perimeter=True)],
            existing_publication_by_doi={},
        )
        assert _groups(plan) == {None: (1,)}

    def test_materialized_without_carrier_prefers_external_carrier(self):
        """enregistrement source matérialisé sur une publication qui n'a pas le DOI (dérive) → ancre = porteur externe,
        la publication dérivée est dissoute vers lui."""
        plan = plan_reconciliation(
            [_m(1, 50, doi="10.1/x", tokens=[("doi", "10.1/x")])],  # publication 50 n'a pas X
            existing_publication_by_doi={"10.1/x": 90},
        )
        assert _groups(plan) == {90: (1,)}
        assert plan.dissolved == (DissolvedPublication(50, 90),)


class TestSingleDoiComponent:
    def test_source_record_without_doi_joins_the_partition(self):
        """Composante à un seul DOI : l'enregistrement source sans DOI fait partie de la partition, sa publication est absorbée."""
        plan = plan_reconciliation(
            [
                _m(
                    1,
                    10,
                    publication_doi="10.1/x",
                    doi="10.1/x",
                    tokens=[("hal_id", "h"), ("doi", "10.1/x")],
                ),
                _m(2, 20, tokens=[("hal_id", "h")]),
            ]
        )
        assert _groups(plan) == {10: (1, 2)}
        assert plan.dissolved == (DissolvedPublication(20, 10),)


class TestCompetingClaims:
    """Deux partitions revendiquent la même publication : une seule la garde."""

    def test_doi_carrier_beats_a_weak_claim_with_a_smaller_source_record(self):
        plan = plan_reconciliation(
            [
                _m(
                    1,
                    10,
                    publication_doi="10.1/x",
                    doi="10.2/y",
                    tokens=[("hal_id", "h"), ("doi", "10.2/y")],
                ),
                _m(
                    5,
                    10,
                    publication_doi="10.1/x",
                    doi="10.1/x",
                    tokens=[("hal_id", "h"), ("doi", "10.1/x")],
                ),
            ]
        )
        assert _groups(plan) == {10: (5,), None: (1,)}

    def test_between_weak_claims_the_smallest_source_record_wins(self):
        plan = plan_reconciliation(
            [
                _m(5, 10, doi="10.1/x", tokens=[("hal_id", "h"), ("doi", "10.1/x")]),
                _m(2, 10, doi="10.2/y", tokens=[("hal_id", "h"), ("doi", "10.2/y")]),
            ]
        )
        assert _groups(plan) == {10: (2,), None: (5,)}

    def test_external_carrier_beats_a_weak_claim_with_a_smaller_source_record(self):
        plan = plan_reconciliation(
            [
                _m(1, 90, publication_doi="10.1/x", doi="10.2/y", tokens=[("hal_id", "a")]),
                _m(5, 50, doi="10.1/x", tokens=[("hal_id", "b")]),
            ],
            existing_publication_by_doi={"10.1/x": 90},
        )
        assert _groups(plan) == {90: (5,), None: (1,)}

    def test_external_carrier_of_orphans_beats_a_weak_claim_with_a_smaller_source_record(self):
        plan = plan_reconciliation(
            [
                _m(1, 90, publication_doi="10.1/x", doi="10.2/y", tokens=[("hal_id", "a")]),
                _m(5, None, doi="10.1/x", tokens=[("hal_id", "b")]),
            ],
            existing_publication_by_doi={"10.1/x": 90},
        )
        assert _groups(plan) == {90: (5,), None: (1,)}


class TestDissolution:
    def test_publication_retaining_a_residual_source_record_is_kept(self):
        """La publication 30 perd l'enregistrement source 1 mais garde l'enregistrement source résiduel 3 : elle n'est pas dissoute."""
        plan = plan_reconciliation(
            [
                _m(1, 30, doi="10.1/x", tokens=[("hal_id", "h"), ("doi", "10.1/x")]),
                _m(
                    4,
                    40,
                    publication_doi="10.1/x",
                    doi="10.1/x",
                    tokens=[("hal_id", "h"), ("doi", "10.1/x")],
                ),
                _m(
                    2,
                    20,
                    publication_doi="10.2/y",
                    doi="10.2/y",
                    tokens=[("hal_id", "h"), ("doi", "10.2/y")],
                ),
                _m(3, 30, tokens=[("hal_id", "h")]),
            ]
        )
        assert _groups(plan) == {40: (1, 4), 20: (2,)}
        assert plan.dissolved == ()

    def test_successor_follows_the_smallest_source_record_of_the_dissolved_publication(self):
        """La publication 50 éclate entre les publications 70 et 30 : son successeur est celui de son enregistrement source 3."""
        plan = plan_reconciliation(
            [
                _m(7, 50, doi="10.1/x", tokens=[("hal_id", "h"), ("doi", "10.1/x")]),
                _m(3, 50, doi="10.2/y", tokens=[("hal_id", "h"), ("doi", "10.2/y")]),
                _m(
                    8,
                    70,
                    publication_doi="10.1/x",
                    doi="10.1/x",
                    tokens=[("hal_id", "h"), ("doi", "10.1/x")],
                ),
                _m(
                    4,
                    30,
                    publication_doi="10.2/y",
                    doi="10.2/y",
                    tokens=[("hal_id", "h"), ("doi", "10.2/y")],
                ),
            ]
        )
        assert _groups(plan) == {70: (7, 8), 30: (3, 4)}
        assert plan.dissolved == (DissolvedPublication(50, 30),)


class TestWorkGroupShape:
    def test_group_source_record_ids_sorted(self):
        plan = plan_reconciliation(
            [
                _m(7, 10, doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(2, 10, doi="10.1/x", tokens=[("doi", "10.1/x")]),
            ]
        )
        assert plan.groups == (WorkGroup(10, (2, 7)),)
