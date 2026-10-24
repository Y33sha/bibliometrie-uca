"""Tests de l'assemblage des arêtes des signaux #2 (clés partagées) et #3 (rapprochement par titre), et de ce que la phase journalise de ses changements."""

import logging

from domain.publications.relations import RelationType
from pipeline.transformation.publications.relations import (
    DeclaredRelationSource,
    DoiPublication,
    RelationEdge,
    RelationsRebuild,
    SharedKeyPair,
    TitleMatch,
    _build_distinct_work_edges,
    _build_shared_key_edges,
    _build_title_match_edges,
    _count_by_pair_label,
    _declared_pairs,
    _log_changes,
)


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
        assert edges[0].target_publication_id == 10

    def test_pair_without_doi_related_by_publication_id(self):
        """Deux publications sans DOI qui partagent une clé sont reliées : la cible est désignée par son identifiant."""
        edges = _build_shared_key_edges(
            [SharedKeyPair(30, "conference_paper", None, 40, "poster", None)], declared_pairs=set()
        )
        assert [
            (e.from_publication_id, e.relation_type, e.target_doi, e.target_publication_id)
            for e in edges
        ] == [(30, "is_related_to", None, 40)]

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


class TestDeclaredPairs:
    """Les paires déclarées se déduisent des arêtes du run, et non de la table du run précédent."""

    def test_cible_resolue_par_son_doi(self):
        edges = [RelationEdge(10, "is_supplement_to", "10.1/b", "datacite")]
        pairs = _declared_pairs(edges, {"10.1/b": DoiPublication(20, "article")})
        assert pairs == {frozenset((10, 20))}

    def test_cible_designee_par_son_identifiant(self):
        edges = [RelationEdge(20, "is_preprint_of", "10.1/a", "datacite", target_publication_id=10)]
        assert _declared_pairs(edges, {}) == {frozenset((10, 20))}

    def test_cible_hors_corpus_ignoree(self):
        edges = [RelationEdge(10, "is_supplement_to", "10.9/ailleurs", "crossref")]
        assert _declared_pairs(edges, {}) == set()


def _source_record(doc_type, relation_type, cible, doi):
    """Enregistrement source DataCite de la publication 1, déclarant une relation de même œuvre."""
    return DeclaredRelationSource(
        publication_id=1,
        source="datacite",
        source_extras={"related_identifiers": [{"relation_type": relation_type, "doi": cible}]},
        doi=doi,
        doc_type=doc_type,
        source_record_doc_type=doc_type,
    )


class TestBuildDistinctWorkEdges:
    def test_preprint_face_a_l_article_publie(self):
        source_record = _source_record(
            "preprint", "IsVersionOf", "10.1007/article", "10.48550/arxiv.1"
        )
        edges = _build_distinct_work_edges(
            [source_record], {"10.1007/article": DoiPublication(2, "article")}
        )
        assert [(e.from_publication_id, e.relation_type, e.target_doi) for e in edges] == [
            (1, "is_preprint_of", "10.1007/article")
        ]

    def test_la_cible_preprint_porte_la_relation(self):
        """Un article déclare une version vers le preprint d'un autre registrant : le preprint est sujet."""
        source_record = _source_record(
            "article", "IsVersionOf", "10.48550/arxiv.2", "10.1103/article"
        )
        edges = _build_distinct_work_edges(
            [source_record], {"10.48550/arxiv.2": DoiPublication(3, "preprint")}
        )
        assert [
            (e.from_publication_id, e.relation_type, e.target_publication_id) for e in edges
        ] == [(3, "is_preprint_of", 1)]

    def test_copie_de_preprint_face_a_l_article(self):
        source_record = _source_record(
            "preprint", "IsVariantFormOf", "10.1140/article", "10.3204/pubdb-1"
        )
        edges = _build_distinct_work_edges(
            [source_record], {"10.1140/article": DoiPublication(4, "article")}
        )
        assert [(e.from_publication_id, e.relation_type) for e in edges] == [(1, "is_preprint_of")]

    def test_copie_de_l_article_ne_donne_aucune_relation(self):
        """La copie de repository de l'article publié rejoint l'article à la déduplication."""
        source_record = _source_record(
            "article", "IsVariantFormOf", "10.1103/article", "10.18154/rwth-1"
        )
        edges = _build_distinct_work_edges(
            [source_record], {"10.1103/article": DoiPublication(4, "article")}
        )
        assert edges == []

    def test_une_cible_hors_corpus_reste_a_qualifier(self):
        source_record = _source_record(
            "article", "IsVersionOf", "10.48550/arxiv.2", "10.18154/rwth-1"
        )
        edges = _build_distinct_work_edges([source_record], {})
        assert [(e.from_publication_id, e.relation_type, e.target_doi) for e in edges] == [
            (1, "is_related_to", "10.48550/arxiv.2")
        ]

    def test_un_preprint_face_a_une_cible_hors_corpus_en_reste_sujet(self):
        source_record = _source_record(
            "preprint", "IsVersionOf", "10.1007/article", "10.48550/arxiv.1"
        )
        edges = _build_distinct_work_edges([source_record], {})
        assert [(e.from_publication_id, e.relation_type, e.target_doi) for e in edges] == [
            (1, "is_preprint_of", "10.1007/article")
        ]

    def test_meme_registrant_sans_relation(self):
        source_record = _source_record(
            "dataset", "IsVersionOf", "10.5281/zenodo.1", "10.5281/zenodo.10"
        )
        assert _build_distinct_work_edges([source_record], {}) == []


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


class TestChangementsJournalises:
    """Le journal dit les relations ajoutées depuis le run précédent, dans les mots d'un lecteur."""

    def test_un_type_et_son_inverse_comptent_pour_un_meme_lien(self):
        compte = _count_by_pair_label([("is_preprint_of", 6), ("has_preprint", 2)])

        assert compte == {"préprint/article": 8}

    def test_les_liens_les_plus_nombreux_viennent_en_tete(self):
        compte = _count_by_pair_label([("is_correction_of", 1), ("is_supplement_to", 3)])

        assert list(compte) == ["article/données supplémentaires", "article/erratum"]

    def test_le_journal_nomme_les_liens_et_non_les_types(self, caplog):
        logger = logging.getLogger("test_relations")
        with caplog.at_level(logging.INFO, logger=logger.name):
            _log_changes(RelationsRebuild(4569, [("is_preprint_of", 8)], removed=4), logger)

        assert caplog.messages[-5:] == [
            "▶ Relations entre publications",
            "  ├─ 8 nouvelles relations, dont",
            "  │  8 préprint/article",
            "  │",
            "  └─ 4 relations retirées",
        ]
        assert "is_preprint_of" not in caplog.text

    def test_une_reconstruction_a_l_identique_ne_dit_rien_de_plus(self, caplog):
        logger = logging.getLogger("test_relations")
        with caplog.at_level(logging.INFO, logger=logger.name):
            _log_changes(RelationsRebuild(4569, [], removed=0), logger)

        assert "aucun changement" in caplog.text
        # Le nombre d'arêtes réécrites ne paraît pas : la table est reconstruite entière.
        assert "4569" not in caplog.text
