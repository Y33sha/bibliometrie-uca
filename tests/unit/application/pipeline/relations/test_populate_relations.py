"""Tests de l'assemblage des arêtes des signaux #2 (clés partagées) et #3 (rapprochement par titre), et de ce que la phase journalise de ses changements."""

import logging

from application.pipeline.relations.phase import (
    _build_distinct_work_edges,
    _build_shared_key_edges,
    _build_title_match_edges,
    _count_by_pair_label,
    _log_changes,
)
from application.ports.pipeline.relations import (
    DeclaredRelationSource,
    DoiPublication,
    RelationsRebuild,
    SharedKeyPair,
    TitleMatch,
)
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


def _notice(doc_type, relation_type, cible, doi):
    """Notice DataCite de la publication 1, déclarant une relation de même œuvre."""
    return DeclaredRelationSource(
        publication_id=1,
        source="datacite",
        meta={"related_identifiers": [{"relation_type": relation_type, "doi": cible}]},
        doi=doi,
        doc_type=doc_type,
    )


class TestBuildDistinctWorkEdges:
    def test_preprint_face_a_l_article_publie(self):
        notice = _notice("preprint", "IsVersionOf", "10.1007/article", "10.48550/arxiv.1")
        edges = _build_distinct_work_edges(
            [notice], {"10.1007/article": DoiPublication(2, "article")}
        )
        assert [(e.from_publication_id, e.relation_type, e.target_doi) for e in edges] == [
            (1, "is_preprint_of", "10.1007/article")
        ]

    def test_la_cible_preprint_porte_la_relation(self):
        """Une copie de dépôt déclare une variante vers le preprint : le preprint est sujet."""
        notice = _notice("article", "IsVariantFormOf", "10.48550/arxiv.2", "10.18154/rwth-1")
        edges = _build_distinct_work_edges(
            [notice], {"10.48550/arxiv.2": DoiPublication(3, "preprint")}
        )
        assert [
            (e.from_publication_id, e.relation_type, e.target_publication_id) for e in edges
        ] == [(3, "is_preprint_of", 1)]

    def test_deux_articles_restent_a_qualifier(self):
        notice = _notice("article", "IsVariantFormOf", "10.1103/article", "10.18154/rwth-1")
        edges = _build_distinct_work_edges(
            [notice], {"10.1103/article": DoiPublication(4, "article")}
        )
        assert [e.relation_type for e in edges] == ["is_related_to"]

    def test_une_cible_hors_corpus_ne_donne_aucune_relation(self):
        notice = _notice("preprint", "IsVersionOf", "10.1007/article", "10.48550/arxiv.1")
        assert _build_distinct_work_edges([notice], {}) == []

    def test_meme_registrant_sans_relation(self):
        notice = _notice("dataset", "IsVersionOf", "10.5281/zenodo.1", "10.5281/zenodo.10")
        assert _build_distinct_work_edges([notice], {}) == []


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

        assert compte == {"préprint – article": 8}

    def test_les_liens_les_plus_nombreux_viennent_en_tete(self):
        compte = _count_by_pair_label([("is_correction_of", 1), ("is_supplement_to", 3)])

        assert list(compte) == ["article – données supplémentaires", "article – erratum"]

    def test_le_journal_nomme_les_liens_et_non_les_types(self, caplog):
        logger = logging.getLogger("test_relations")
        with caplog.at_level(logging.INFO, logger=logger.name):
            _log_changes(RelationsRebuild(4569, [("is_preprint_of", 8)], removed=4), logger)

        assert "8 nouvelles relations entre publications" in caplog.text
        assert "préprint – article" in caplog.text
        assert "4 relations retirées" in caplog.text
        assert "is_preprint_of" not in caplog.text

    def test_une_reconstruction_a_l_identique_ne_dit_rien_de_plus(self, caplog):
        logger = logging.getLogger("test_relations")
        with caplog.at_level(logging.INFO, logger=logger.name):
            _log_changes(RelationsRebuild(4569, [], removed=0), logger)

        assert "aucun changement" in caplog.text
        # Le nombre d'arêtes réécrites ne paraît pas : la table est reconstruite entière.
        assert "4569" not in caplog.text
