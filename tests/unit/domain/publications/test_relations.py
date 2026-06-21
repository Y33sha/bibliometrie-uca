"""Tests du mapping des relations sources → vocabulaire canonique."""

from domain.publications.relations import (
    RelationType,
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
