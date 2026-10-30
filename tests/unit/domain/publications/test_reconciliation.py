"""`plan_reconciliation` : rattachement des enregistrements sources d'un voisinage à leur publication d'ancrage, avec fusion, scission et création de publications.

Un enregistrement source sans publication (`publication_id=None`) est orphelin.
"""

from domain.publications.reconciliation import (
    DissolvedPublication,
    ReconcileMember,
    WorkGroup,
    plan_reconciliation,
)
from domain.source_records.keys import DoiKeys


def _m(
    source_record_id,
    publication_id,
    *,
    publication_doi=None,
    doi=None,
    weak=(),
    tokens=(),
    in_perimeter=False,
    tn="t",
    year=2024,
    doc_type=None,
    matchable=True,
):
    """Construit un membre du voisinage.

    Args:
        doi: DOI primaire.
        weak: DOI secondaires.
    """
    return ReconcileMember(
        source_record_id=source_record_id,
        publication_id=publication_id,
        publication_doi=publication_doi,
        doi_keys=DoiKeys(frozenset({doi} if doi else ()), frozenset(weak)),
        tokens=frozenset(tokens),
        in_perimeter=in_perimeter,
        title_normalized=tn,
        publication_year=year,
        doc_type=doc_type,
        matchable=matchable,
    )


def _groups(plan):
    return {g.target_publication_id: g.source_record_ids for g in plan.groups}


class TestMerge:
    def test_two_publications_same_doi_merge_to_carrier(self):
        """Les enregistrements sources de deux publications partagent un DOI : elles fusionnent dans celle de plus petit identifiant."""
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
        """Composante sans DOI, reliée par l'identifiant HAL, sur deux publications : l'ancre est la publication du plus petit enregistrement source."""
        plan = plan_reconciliation(
            [
                _m(5, 50, tokens=[("hal_id", "hal-1")]),
                _m(3, 30, tokens=[("hal_id", "hal-1")]),
            ]
        )
        assert _groups(plan) == {
            30: (3, 5)
        }  # plus petit enregistrement source : 3, de la publication 30
        assert plan.dissolved == (DissolvedPublication(50, 30),)

    def test_single_publication_stable(self):
        """Une seule publication : un groupe sur elle-même, aucune dissolution."""
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
        """L'ancre est la publication qui a le DOI, même si une autre publication a un enregistrement source plus petit."""
        plan = plan_reconciliation(
            [
                _m(
                    1, 50, doi="10.1/x", tokens=[("doi", "10.1/x")]
                ),  # la publication 50 est sans le DOI
                _m(
                    9, 90, publication_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]
                ),  # la publication 90 a le DOI
            ]
        )
        # Plus petit enregistrement source : 1, de la publication 50 ; l'ancre est 90, qui a le DOI.
        assert _groups(plan) == {90: (1, 9)}
        assert plan.dissolved == (DissolvedPublication(50, 90),)


class TestSplit:
    def test_publication_with_two_dois_splits(self):
        """Une publication de DOI X contient un enregistrement source de DOI Y, relié par l'identifiant HAL : X garde la publication, Y en fonde une autre."""
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
        }  # X garde la publication 10 ; Y va à une publication à créer
        assert plan.dissolved == ()  # la publication 10 reste, ancre de X

    def test_residual_no_doi_source_record_stays(self):
        """Composante à plusieurs DOI : l'enregistrement source sans DOI est résiduel ; il reste sur sa publication, qui est conservée."""
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
                _m(3, 30, tokens=[("hal_id", "h")]),  # sans DOI : résiduel
            ]
        )
        assert _groups(plan) == {10: (1,), 20: (2,)}
        # La publication 30 garde l'enregistrement source résiduel 3 : elle est conservée.
        assert plan.dissolved == ()


class TestDoiAnchors:
    """Coupe par les ancres : DOI primaires ou dérivés, à défaut DOI des membres qui en ont un seul."""

    def test_secondary_doi_shared_with_the_anchor_keeps_the_component_whole(self):
        """Un enregistrement source OpenAlex cite le DOI de l'article et celui d'une copie d'archive, en DOI secondaires."""
        plan = plan_reconciliation(
            [
                _m(1, 10, doi="10.1/article", tokens=[("doi", "10.1/article")]),
                _m(
                    2,
                    20,
                    weak=("10.1/article", "10.9/copie"),
                    tokens=[("doi", "10.1/article"), ("doi", "10.9/copie")],
                ),
            ]
        )
        assert _groups(plan) == {10: (1, 2)}
        assert plan.groups[0].doi == "10.1/article"

    def test_secondary_dois_alone_anchor_the_component(self):
        """Un dépôt HAL et un enregistrement source WoS partagent un DOI secondaire."""
        plan = plan_reconciliation(
            [
                _m(1, 10, weak=("10.1/x",), tokens=[("doi", "10.1/x")]),
                _m(2, 20, weak=("10.1/x",), tokens=[("doi", "10.1/x")]),
            ]
        )
        assert _groups(plan) == {10: (1, 2)}
        assert plan.groups[0].doi == "10.1/x"

    def test_member_joins_the_anchor_of_its_primary_or_derived_doi(self):
        """Un enregistrement source scanR : DOI dérivé de l'article, DOI secondaire du preprint."""
        plan = plan_reconciliation(
            [
                _m(1, 10, doi="10.1/article", tokens=[("doi", "10.1/article")]),
                _m(2, 20, doi="10.1101/preprint", tokens=[("doi", "10.1101/preprint")]),
                _m(
                    3,
                    20,
                    doi="10.1/article",
                    weak=("10.1101/preprint",),
                    tokens=[("doi", "10.1/article"), ("doi", "10.1101/preprint")],
                ),
            ]
        )
        assert _groups(plan) == {10: (1, 3), 20: (2,)}

    def test_member_without_a_unique_anchor_stays_on_its_publication(self):
        """Un enregistrement source OpenAlex cite en DOI secondaires l'article et le preprint, deux ancres."""
        plan = plan_reconciliation(
            [
                _m(1, 10, doi="10.1/article", tokens=[("doi", "10.1/article")]),
                _m(2, 20, doi="10.48550/arxiv.1", tokens=[("doi", "10.48550/arxiv.1")]),
                _m(
                    3,
                    30,
                    weak=("10.1/article", "10.48550/arxiv.1"),
                    tokens=[("doi", "10.1/article"), ("doi", "10.48550/arxiv.1")],
                ),
            ]
        )
        assert _groups(plan) == {10: (1,), 20: (2,)}
        assert plan.dissolved == ()


class TestDetachment:
    def test_enregistrement_source_sans_cle_ni_annee_est_detache(self):
        """Un enregistrement source OpenAlex renvoyé sans DOI ni année perd toutes ses clés ; il ne peut fonder aucune publication et devient orphelin."""
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
    """Enregistrements sources écartés (`matchable` faux) : hors de toute partition, détachés s'ils sont matérialisés."""

    def test_excluded_record_is_detached_from_its_publication(self):
        plan = plan_reconciliation(
            [
                _m(1, 10, publication_doi="10.1/x", doi="10.1/x", tokens=[("hal_id", "hal-1")]),
                _m(2, 10, tokens=[("hal_id", "hal-1")], matchable=False),
            ]
        )
        assert _groups(plan) == {10: (1,)}
        assert plan.detached == (2,)
        assert plan.dissolved == ()

    def test_publication_of_excluded_records_only_is_not_dissolved(self):
        """Une publication faite de copies GRESIS perd tous ses enregistrements sources, sans successeur. Le recalcul la supprime."""
        gresis = "10.60692/m2raz-tjw54"
        plan = plan_reconciliation(
            [
                _m(
                    1,
                    10,
                    publication_doi=gresis,
                    doi=gresis,
                    tokens=[("doi", gresis)],
                    matchable=False,
                ),
                _m(
                    2,
                    10,
                    publication_doi=gresis,
                    doi=gresis,
                    tokens=[("doi", gresis)],
                    matchable=False,
                ),
            ],
            publication_sizes={10: 2},
        )
        assert plan.groups == ()
        assert plan.detached == (1, 2)
        assert plan.dissolved == ()

    def test_excluded_orphan_founds_nothing(self):
        plan = plan_reconciliation([_m(1, None, in_perimeter=True, matchable=False)])
        assert plan.groups == ()
        assert plan.detached == ()

    def test_excluded_record_does_not_bridge_two_works(self):
        """Un enregistrement source écarté partage une clé avec deux œuvres. Les deux œuvres restent distinctes."""
        plan = plan_reconciliation(
            [
                _m(1, 10, tokens=[("hal_id", "hal-1")]),
                _m(2, 20, tokens=[("pmid", "42")]),
                _m(3, 10, tokens=[("hal_id", "hal-1"), ("pmid", "42")], matchable=False),
            ]
        )
        assert _groups(plan) == {10: (1,), 20: (2,)}
        assert plan.detached == (3,)
        assert plan.dissolved == ()

    def test_merged_publication_with_excluded_record_dissolves_into_successor(self):
        """La publication 20 cède un enregistrement source à 10, et son plus petit enregistrement source est écarté. Elle est dissoute vers 10."""
        plan = plan_reconciliation(
            [
                _m(1, 20, tokens=(), matchable=False),
                _m(2, 10, tokens=[("hal_id", "hal-1")]),
                _m(3, 20, tokens=[("hal_id", "hal-1")]),
            ]
        )
        assert _groups(plan) == {10: (2, 3)}
        assert plan.detached == (1,)
        assert plan.dissolved == (DissolvedPublication(20, 10),)


class TestAssignmentOfOrphans:
    """Enregistrements sources orphelins : rattachement, création de publication ou abstention."""

    def test_match_orphan_joins_existing_publication(self):
        """Un orphelin rejoint la publication existante qui a son DOI."""
        plan = plan_reconciliation(
            [
                _m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(2, 50, publication_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]),
            ]
        )
        assert _groups(plan) == {50: (1, 2)}
        assert plan.dissolved == ()

    def test_create_orphans_with_perimeter(self):
        """Orphelins seuls, dont un au moins dans le périmètre : une publication est créée."""
        plan = plan_reconciliation(
            [
                _m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")], in_perimeter=True),
                _m(
                    2, None, doi="10.1/x", tokens=[("doi", "10.1/x")]
                ),  # hors du périmètre, voisin d'un orphelin du périmètre
            ]
        )
        assert _groups(plan) == {None: (1, 2)}
        assert plan.dissolved == ()

    def test_skip_orphans_out_of_perimeter(self):
        """Orphelins seuls, tous hors du périmètre : aucun groupe."""
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
        """Aucun enregistrement source ne fonde de publication : l'un est d'un type non admissible, l'autre est hors du périmètre."""
        key = [("hal_id", "dumas-01234567")]
        plan = plan_reconciliation(
            [
                _m(1, None, tokens=key, in_perimeter=True, doc_type="memoir"),
                _m(2, None, tokens=key, in_perimeter=False, doc_type="article"),
            ]
        )
        assert plan.groups == ()

    def test_one_member_able_to_found_a_publication_creates(self):
        """Un enregistrement source du périmètre, d'un type admissible, suffit ; le type de la publication est arbitré au recalcul des métadonnées."""
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
        """Orphelins du périmètre, sans titre ou sans année : aucune création (règle de `has_minimal_publication_metadata`)."""
        plan = plan_reconciliation(
            [
                _m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")], in_perimeter=True, year=None),
                _m(2, None, doi="10.1/x", tokens=[("doi", "10.1/x")], in_perimeter=True, tn=""),
            ]
        )
        assert plan.groups == ()  # aucun membre matérialisable

    def test_mixed_orphan_matches_other_orphan_skipped(self):
        """Un orphelin rejoint la publication de DOI X ; un autre, de DOI Y et hors du périmètre, reste orphelin."""
        plan = plan_reconciliation(
            [
                _m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(2, 50, publication_doi="10.1/x", doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(3, None, doi="10.2/y", tokens=[("doi", "10.2/y")]),
            ]
        )
        assert _groups(plan) == {
            50: (1, 2)
        }  # l'enregistrement source 3 (DOI Y, hors du périmètre) reste hors groupe
        assert plan.dissolved == ()


class TestExternalDoiCarrier:
    """Publication du DOI hors du voisinage : elle a le DOI, mais aucun enregistrement source du voisinage ne lui est rattaché.

    Le groupe s'ancre sur elle : une publication créée avec le même DOI violerait la contrainte d'unicité.
    """

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
        """Sans publication connue du DOI, une publication est créée."""
        plan = plan_reconciliation(
            [_m(1, None, doi="10.1/x", tokens=[("doi", "10.1/x")], in_perimeter=True)],
            existing_publication_by_doi={},
        )
        assert _groups(plan) == {None: (1,)}

    def test_materialized_without_carrier_prefers_external_carrier(self):
        """Enregistrement source rattaché à une publication sans le DOI : l'ancre est la publication du DOI hors du voisinage, vers laquelle sa publication est dissoute."""
        plan = plan_reconciliation(
            [
                _m(1, 50, doi="10.1/x", tokens=[("doi", "10.1/x")])
            ],  # la publication 50 est sans le DOI
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
        """La publication 50 se répartit entre les publications 70 et 30 : son successeur est celui de son enregistrement source 3."""
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
        assert plan.groups == (WorkGroup(10, (2, 7), "10.1/x"),)
