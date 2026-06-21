"""Tests du mapping des relations sources → vocabulaire canonique."""

from domain.publications.relations import (
    RelationType,
    extract_crossref_relations,
    extract_datacite_relations,
    infer_shared_key_relation,
    map_crossref_relation,
    map_datacite_relation,
)


class TestDataciteMapping:
    def test_supplement_and_part(self):
        assert map_datacite_relation("IsSupplementTo") == RelationType.IS_SUPPLEMENT_TO
        assert map_datacite_relation("IsSupplementedBy") == RelationType.HAS_SUPPLEMENT
        assert map_datacite_relation("IsPartOf") == RelationType.IS_PART_OF
        assert map_datacite_relation("HasPart") == RelationType.HAS_PART

    def test_describes_family(self):
        assert map_datacite_relation("Describes") == RelationType.DESCRIBES
        assert map_datacite_relation("IsDescribedBy") == RelationType.IS_DESCRIBED_BY
        assert map_datacite_relation("IsDocumentedBy") == RelationType.IS_DESCRIBED_BY

    def test_out_of_scope(self):
        # Citations, même-œuvre, peer-review, vague.
        for raw in ("References", "Cites", "IsVersionOf", "IsVariantFormOf", "IsReviewedBy"):
            assert map_datacite_relation(raw) is None

    def test_unknown(self):
        assert map_datacite_relation("WhateverNewType") is None


class TestCrossrefMapping:
    def test_preprint_supplement_translation(self):
        assert map_crossref_relation("is-preprint-of") == RelationType.IS_PREPRINT_OF
        assert map_crossref_relation("has-preprint") == RelationType.HAS_PREPRINT
        assert map_crossref_relation("is-supplement-to") == RelationType.IS_SUPPLEMENT_TO
        assert map_crossref_relation("is-translation-of") == RelationType.IS_TRANSLATION_OF

    def test_correction_family_on_article(self):
        for raw in ("erratum", "correction", "corrigendum", "addendum", "clarification"):
            assert map_crossref_relation(raw) == RelationType.HAS_CORRECTION
        assert map_crossref_relation("corrected") == RelationType.IS_CORRECTION_OF

    def test_retraction_and_concern_family(self):
        assert map_crossref_relation("retraction") == RelationType.HAS_RETRACTION
        assert map_crossref_relation("withdrawal") == RelationType.HAS_RETRACTION
        assert map_crossref_relation("expression_of_concern") == RelationType.HAS_CONCERN

    def test_data_paper_describes(self):
        assert map_crossref_relation("is-part-of") == RelationType.DESCRIBES
        assert map_crossref_relation("has-part") == RelationType.IS_DESCRIBED_BY

    def test_out_of_scope(self):
        # Peer-review / commentaire (porteur peer_review), citations, même-œuvre.
        for raw in ("has-review", "is-review-of", "is-comment-on", "references", "is-version-of"):
            assert map_crossref_relation(raw) is None


class TestExtractDatacite:
    def test_keeps_in_scope_drops_rest(self):
        meta = {
            "related_identifiers": [
                {"doi": "10.1/sup", "relation_type": "IsSupplementTo"},
                {"doi": "10.1/concept", "relation_type": "IsVersionOf"},  # même-œuvre → exclu
                {"doi": "10.1/cited", "relation_type": "References"},  # citation → exclu
                {"relation_type": "IsSupplementTo"},  # sans DOI → ignoré
            ]
        }
        assert extract_datacite_relations(meta) == [(RelationType.IS_SUPPLEMENT_TO, "10.1/sup")]

    def test_empty(self):
        assert extract_datacite_relations({}) == []
        assert extract_datacite_relations(None) == []


class TestExtractCrossref:
    def test_keeps_doi_targets_in_scope(self):
        meta = {
            "relation": {
                "is-preprint-of": [{"id": "10.1/pub", "id-type": "doi", "asserted-by": "subject"}],
                "has-review": [{"id": "10.1/rev", "id-type": "doi"}],  # peer-review → exclu
                "is-part-of": [
                    {"id": "10.1/ds", "id-type": "doi"},
                    {"id": "abc", "id-type": "issn"},  # pas un DOI → ignoré
                ],
            }
        }
        assert sorted(extract_crossref_relations(meta)) == sorted(
            [
                (RelationType.IS_PREPRINT_OF, "10.1/pub"),
                (RelationType.DESCRIBES, "10.1/ds"),
            ]
        )

    def test_no_relation(self):
        assert extract_crossref_relations({}) == []
        assert extract_crossref_relations({"relation": None}) == []


class TestInferSharedKeyRelation:
    def test_peer_review_out_of_scope(self):
        assert infer_shared_key_relation("article", "peer_review") is None
        assert infer_shared_key_relation("peer_review", "preprint") is None

    def test_preprint_directed_to_published(self):
        # Le preprint est sujet, pointe vers l'autre bout.
        assert infer_shared_key_relation("article", "preprint") == (
            RelationType.IS_PREPRINT_OF,
            "b",
        )
        assert infer_shared_key_relation("preprint", "conference_paper") == (
            RelationType.IS_PREPRINT_OF,
            "a",
        )

    def test_erratum_and_dataset(self):
        assert infer_shared_key_relation("erratum", "article") == (
            RelationType.IS_CORRECTION_OF,
            "a",
        )
        assert infer_shared_key_relation("article", "dataset") == (
            RelationType.IS_SUPPLEMENT_TO,
            "b",
        )

    def test_book_chapter_is_part_of_book(self):
        assert infer_shared_key_relation("book", "book_chapter") == (RelationType.IS_PART_OF, "b")
        assert infer_shared_key_relation("book_chapter", "book") == (RelationType.IS_PART_OF, "a")

    def test_unexpected_couples_are_undefined(self):
        # Deux exemplaires d'une même œuvre à DOI distincts, ou couple non typé : apparenté.
        for a, b in [
            ("article", "article"),
            ("article", "conference_paper"),
            ("review", "review"),
            ("preprint", "preprint"),  # deux preprints : aucun n'est sujet unique
            ("thesis", "thesis"),
        ]:
            assert infer_shared_key_relation(a, b) == (RelationType.IS_RELATED_TO, "sym")
