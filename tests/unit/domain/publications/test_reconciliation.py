"""`plan_reconciliation` : rattachement des enregistrements sources d'un voisinage à leur publication d'ancrage, avec fusion, scission et création de publications.

Un enregistrement source sans publication (`publication_id=None`) est orphelin.
"""

from dataclasses import replace

from domain.publications.reconciliation import (
    DissolvedPublication,
    ReconcileMember,
    WorkGroup,
    plan_reconciliation,
)
from domain.source_records.keys import Derivation, DoiKeys


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
    primary=None,
    derived=None,
    work_id=None,
):
    """Construit un membre du voisinage.

    Args:
        doi: DOI primaire.
        weak: DOI secondaires.
        primary: identifiant primaire, en couple (type, valeur).
        derived: identifiant dérivé, en couple (type, valeur).
        work_id: clé d'un enregistrement source d'œuvre, comme une famille de brevets.
    """
    return ReconcileMember(
        source_record_id=source_record_id,
        publication_id=publication_id,
        publication_doi=publication_doi,
        doi_keys=DoiKeys(frozenset({doi} if doi else ()), frozenset(weak)),
        tokens=frozenset(tokens),
        derivation=Derivation(primary, derived),
        work_id=work_id,
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

    def test_bridge_without_doi_forms_its_own_partition(self):
        """Composante à plusieurs DOI : l'enregistrement source sans DOI relie les deux ancres ; il forme sa propre partition, sur sa publication."""
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
                _m(3, 30, tokens=[("hal_id", "h")]),
            ]
        )
        assert _groups(plan) == {10: (1,), 20: (2,), 30: (3,)}
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
        """Un enregistrement source scanR : DOI dérivé de l'article, DOI secondaire de la communication."""
        plan = plan_reconciliation(
            [
                _m(1, 10, doi="10.1/article", tokens=[("doi", "10.1/article")]),
                _m(2, 20, doi="10.2/communication", tokens=[("doi", "10.2/communication")]),
                _m(
                    3,
                    20,
                    doi="10.1/article",
                    weak=("10.2/communication",),
                    tokens=[("doi", "10.1/article"), ("doi", "10.2/communication")],
                ),
            ]
        )
        assert _groups(plan) == {10: (1, 3), 20: (2,)}

    def test_member_without_a_unique_anchor_forms_its_own_partition(self):
        """Un enregistrement source OpenAlex cite en DOI secondaires l'article et la communication, deux ancres."""
        plan = plan_reconciliation(
            [
                _m(1, 10, doi="10.1/article", tokens=[("doi", "10.1/article")]),
                _m(2, 20, doi="10.2/communication", tokens=[("doi", "10.2/communication")]),
                _m(
                    3,
                    30,
                    weak=("10.1/article", "10.2/communication"),
                    tokens=[("doi", "10.1/article"), ("doi", "10.2/communication")],
                ),
            ]
        )
        assert _groups(plan) == {10: (1,), 20: (2,), 30: (3,)}
        assert plan.dissolved == ()


_ARXIV = "10.48550/arxiv.1"


def _preprint_component(*, doc_type=None):
    """Composante à deux ancres, l'article et la communication, et un preprint arXiv sur deux publications, 30 et 40. Les enregistrements sources 6 et 7 citent le DOI arXiv à côté de l'article et de la communication."""
    return [
        _m(1, 10, doi="10.1/article", tokens=[("doi", "10.1/article")], doc_type="article"),
        _m(
            2,
            20,
            doi="10.2/communication",
            tokens=[("doi", "10.2/communication")],
            doc_type="conference_paper",
        ),
        _m(4, 30, weak=(_ARXIV,), tokens=[("doi", _ARXIV)], doc_type=doc_type),
        _m(5, 40, doi=_ARXIV, tokens=[("doi", _ARXIV)], doc_type=doc_type),
        _m(
            6,
            10,
            weak=("10.1/article", _ARXIV),
            tokens=[("doi", "10.1/article"), ("doi", _ARXIV)],
            doc_type="article",
        ),
        _m(
            7,
            20,
            weak=("10.2/communication", _ARXIV),
            tokens=[("doi", "10.2/communication"), ("doi", _ARXIV)],
            doc_type="conference_paper",
        ),
    ]


class TestBridges:
    """Dans une composante à plusieurs ancres, les enregistrements sources sans ancre forment des sous-composantes."""

    def test_records_of_a_bridge_stay_together(self):
        """Le preprint relie l'article et la communication : ses deux publications fusionnent, hors des deux ancres."""
        plan = plan_reconciliation(_preprint_component(doc_type="preprint"))

        assert _groups(plan) == {10: (1, 6), 20: (2, 7), 30: (4, 5)}
        assert plan.dissolved == (DissolvedPublication(40, 30),)

    def test_a_bridge_joins_the_only_anchor_of_its_doc_type(self):
        plan = plan_reconciliation(_preprint_component(doc_type="article"))

        assert _groups(plan) == {10: (1, 4, 5, 6), 20: (2, 7)}
        assert plan.dissolved == (DissolvedPublication(30, 10), DissolvedPublication(40, 10))

    def test_a_subcomponent_linked_to_one_anchor_joins_it(self):
        """Seul l'enregistrement source 6 cite le DOI arXiv à côté d'une ancre : le preprint rejoint l'article."""
        members = [m for m in _preprint_component(doc_type="preprint") if m.source_record_id != 7]
        members.append(
            _m(
                3,
                10,
                doi="10.1/article",
                weak=("10.2/communication",),
                tokens=[("doi", "10.1/article"), ("doi", "10.2/communication")],
            )
        )

        plan = plan_reconciliation(members)

        assert _groups(plan) == {10: (1, 3, 4, 5, 6), 20: (2,)}
        assert plan.dissolved == (DissolvedPublication(30, 10), DissolvedPublication(40, 10))


_BLOCK = ("metadata_block", "patent|dispositif d eclairage de securite|2022")
"""Bloc de métadonnées commun à deux familles de brevets déposées le même jour sous le même titre."""


def _family(source_record_id, publication_id, family, *tokens):
    return _m(
        source_record_id,
        publication_id,
        tokens=[_BLOCK, *tokens],
        doc_type="patent",
        work_id=f"scanr_patents:{family}",
    )


class TestWorkAnchors:
    """Un enregistrement source d'œuvre, comme une famille de brevets, est une ancre."""

    def test_two_works_with_the_same_metadata_split(self):
        """Deux familles au même bloc de métadonnées : la seconde crée sa publication."""
        plan = plan_reconciliation([_family(1, 10, "A"), _family(2, 10, "B")])

        assert _groups(plan) == {10: (1,), None: (2,)}

    def test_a_record_linked_to_one_work_joins_it(self):
        """Le dépôt HAL partage un numéro de publication avec la seule famille A."""
        number = ("patent_publication_number", "FR3143101")
        deposit = _m(3, 30, tokens=[number], doc_type="patent")

        plan = plan_reconciliation([_family(1, 10, "A", number), _family(2, 10, "B"), deposit])

        assert _groups(plan) == {10: (1, 3), None: (2,)}
        assert plan.dissolved == (DissolvedPublication(30, 10),)

    def test_a_record_linked_to_two_works_forms_its_own_partition(self):
        """Le dépôt HAL a le bloc de métadonnées des deux familles."""
        deposit = _m(3, 30, tokens=[_BLOCK], doc_type="patent")

        plan = plan_reconciliation([_family(1, 10, "A"), _family(2, 10, "B"), deposit])

        assert _groups(plan) == {10: (1,), 30: (3,), None: (2,)}

    def test_a_single_work_keeps_its_component(self):
        deposit = _m(3, 30, tokens=[_BLOCK], doc_type="patent")

        plan = plan_reconciliation([_family(1, 10, "A"), deposit])

        assert _groups(plan) == {10: (1, 3)}


class TestPreprintServerDois:
    """Un DOI de serveur de preprints du registre coupe aucune composante."""

    def test_preprint_joins_its_published_version(self):
        """L'enregistrement source DataCite d'un preprint arXiv et l'article partagent l'identifiant arXiv : le preprint rejoint l'article."""
        plan = plan_reconciliation(
            [
                _m(
                    1,
                    10,
                    publication_doi="10.1/article",
                    doi="10.1/article",
                    tokens=[("doi", "10.1/article"), ("arxiv_id", "1")],
                ),
                _m(
                    2,
                    20,
                    publication_doi="10.48550/arxiv.1",
                    doi="10.48550/arxiv.1",
                    tokens=[("doi", "10.48550/arxiv.1"), ("arxiv_id", "1")],
                ),
            ]
        )
        assert _groups(plan) == {10: (1, 2)}
        assert plan.groups[0].doi == "10.1/article"
        assert plan.dissolved == (DissolvedPublication(20, 10),)

    def test_preprints_of_two_servers_stay_together(self):
        """Le même preprint, déposé sur arXiv et sur Research Square, sans version publiée."""
        plan = plan_reconciliation(
            [
                _m(
                    1,
                    10,
                    doi="10.48550/arxiv.1",
                    tokens=[("doi", "10.48550/arxiv.1"), ("arxiv_id", "1")],
                ),
                _m(
                    2,
                    20,
                    doi="10.21203/rs.3.rs-1/v1",
                    tokens=[("doi", "10.21203/rs.3.rs-1/v1"), ("arxiv_id", "1")],
                ),
            ]
        )
        assert _groups(plan) == {10: (1, 2)}


_HAL = ("hal_id", "hal-1")
_ARTICLE = _m(1, 10, doi="10.1/article", tokens=[("doi", "10.1/article")])
_COMMUNICATION = _m(
    2, 20, doi="10.2/communication", tokens=[("doi", "10.2/communication"), ("pmid", "1")]
)


class TestDerivedRecords:
    """Composante à deux ancres, l'article et la communication : un enregistrement source dérivé suit l'ancre de son parent."""

    def test_un_enregistrement_derive_suit_son_parent(self):
        """Le dépôt HAL cite le DOI de l'article ; l'enregistrement scanR dérivé du dépôt, sans DOI, le suit."""
        hal = _m(
            3,
            30,
            weak=("10.1/article",),
            tokens=[_HAL, ("doi", "10.1/article")],
            primary=_HAL,
        )
        scanr = _m(4, 40, tokens=[_HAL, ("pmid", "1")], derived=_HAL)

        plan = plan_reconciliation([_ARTICLE, _COMMUNICATION, hal, scanr])

        assert _groups(plan) == {10: (1, 3, 4), 20: (2,)}

    def test_sans_parent_les_enregistrements_derives_suivent_l_ancre_de_l_un_d_eux(self):
        """Le dépôt HAL est absent du voisinage : le work OpenAlex dérivé du dépôt cite l'article, l'enregistrement scanR dérivé du dépôt suit."""
        openalex = _m(
            3, 30, weak=("10.1/article",), tokens=[_HAL, ("doi", "10.1/article")], derived=_HAL
        )
        scanr = _m(4, 40, tokens=[_HAL, ("pmid", "1")], derived=_HAL)

        plan = plan_reconciliation([_ARTICLE, _COMMUNICATION, openalex, scanr])

        assert _groups(plan) == {10: (1, 3, 4), 20: (2,)}

    def test_l_ancre_du_parent_l_emporte_sur_celle_de_l_enregistrement_derive(self):
        """Le work OpenAlex dérivé du dépôt HAL cite le DOI de la communication ; il suit le dépôt, qui cite l'article."""
        hal = _m(
            3,
            30,
            weak=("10.1/article",),
            tokens=[_HAL, ("doi", "10.1/article")],
            primary=_HAL,
        )
        openalex = _m(
            4,
            40,
            weak=("10.2/communication",),
            tokens=[_HAL, ("doi", "10.2/communication")],
            derived=_HAL,
        )

        plan = plan_reconciliation([_ARTICLE, _COMMUNICATION, hal, openalex])

        assert _groups(plan) == {10: (1, 3, 4), 20: (2,)}


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


_DATASET = "10.5281/zenodo.1"
"""DOI Zenodo d'un jeu de données : DOI de dépôt pour un preprint (`is_deposit_doi`)."""


def _dois_of_groups(members, plan):
    """Renvoie les DOI actifs de chaque groupe, après les retraits du plan."""
    removed = set(plan.doi_removals)
    by_id = {m.source_record_id: m for m in members}
    return [
        {
            doi
            for source_record_id in g.source_record_ids
            for doi in by_id[source_record_id].doi_keys.all
            if (source_record_id, doi) not in removed
        }
        for g in plan.groups
    ]


class TestUniqueDois:
    """Un DOI appartient à une seule partition."""

    def _preprint_with_a_dataset_doi(self):
        """Un article, un jeu de données Zenodo et deux enregistrements sources du preprint de l'article. L'enregistrement source 3 porte à tort le DOI du jeu de données, DOI de dépôt pour un preprint."""
        return [
            _m(
                1,
                10,
                doi="10.1/article",
                tokens=[("doi", "10.1/article"), ("pmid", "1")],
                doc_type="article",
            ),
            replace(
                _m(2, 20, tokens=[("doi", _DATASET)], doc_type="dataset"),
                doi_keys=DoiKeys(frozenset({_DATASET}), frozenset(), "dataset"),
            ),
            replace(
                _m(3, 20, tokens=[("doi", _DATASET), ("hal_id", "hal-1")], doc_type="preprint"),
                doi_keys=DoiKeys(frozenset(), frozenset({_DATASET}), "preprint"),
            ),
            _m(4, 20, tokens=[("hal_id", "hal-1"), ("pmid", "1")], doc_type="preprint"),
        ]

    def test_le_doi_reste_a_la_partition_ou_il_est_fort(self):
        """Le preprint, relié à l'article et au jeu de données, forme un pont sans ancre de son type. Il perd le DOI du jeu de données, puis rejoint l'article, seule ancre qui lui reste reliée."""
        members = self._preprint_with_a_dataset_doi()
        plan = plan_reconciliation(members)

        assert plan.doi_removals == ((3, _DATASET),)
        assert _groups(plan) == {10: (1, 3, 4), 20: (2,)}

    def test_un_doi_fort_nulle_part_est_retire_de_toutes_les_partitions(self):
        """Deux enregistrements sources, chacun ancré par son propre DOI, citent le même DOI d'archive en secondaire."""
        plan = plan_reconciliation(
            [
                _m(
                    1,
                    10,
                    doi="10.1/a",
                    weak=("10.9/copie",),
                    tokens=[("doi", "10.1/a"), ("doi", "10.9/copie")],
                ),
                _m(
                    2,
                    20,
                    doi="10.2/b",
                    weak=("10.9/copie",),
                    tokens=[("doi", "10.2/b"), ("doi", "10.9/copie")],
                ),
            ]
        )
        assert plan.doi_removals == ((1, "10.9/copie"), (2, "10.9/copie"))
        assert _groups(plan) == {10: (1,), 20: (2,)}

    def test_aucun_doi_dans_deux_groupes(self):
        for members in (
            self._preprint_with_a_dataset_doi(),
            _preprint_component(doc_type="preprint"),
        ):
            plan = plan_reconciliation(members)
            dois = _dois_of_groups(members, plan)
            assert all(not (a & b) for i, a in enumerate(dois) for b in dois[i + 1 :])

    def test_sans_doi_partage_aucun_retrait(self):
        plan = plan_reconciliation(
            [
                _m(1, 10, doi="10.1/x", tokens=[("doi", "10.1/x")]),
                _m(2, 10, weak=("10.1/x",), tokens=[("doi", "10.1/x")]),
            ]
        )
        assert plan.doi_removals == ()
