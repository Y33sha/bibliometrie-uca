"""Tests des règles de déduplication / création des publications."""

from domain.publications.deduplication import (
    DeduplicationKey,
    PublicationMatchDecision,
    decide_publication_match,
)

# ── decide_publication_match (cascade pure) ────────────────────────


class TestDecidePublicationMatch:
    def test_no_match_returns_create(self):
        decision = decide_publication_match()
        assert decision == PublicationMatchDecision(
            action="create", publication_id=None, matched_by=None
        )

    def test_doi_wins_over_all(self):
        decision = decide_publication_match(
            doi_merge_with_id=10,
            nnt_match_id=20,
            hal_id_match_id=30,
            pmid_match_id=50,
            thesis_meta_match_id=40,
        )
        assert decision == PublicationMatchDecision(
            action="match", publication_id=10, matched_by=DeduplicationKey.DOI
        )

    def test_nnt_wins_over_hal_and_thesis_meta(self):
        decision = decide_publication_match(
            nnt_match_id=20,
            hal_id_match_id=30,
            thesis_meta_match_id=40,
        )
        assert decision == PublicationMatchDecision(
            action="match", publication_id=20, matched_by=DeduplicationKey.NNT
        )

    def test_hal_wins_over_pmid_and_thesis_meta(self):
        decision = decide_publication_match(
            hal_id_match_id=30,
            pmid_match_id=50,
            thesis_meta_match_id=40,
        )
        assert decision == PublicationMatchDecision(
            action="match", publication_id=30, matched_by=DeduplicationKey.HAL_ID
        )

    def test_pmid_wins_over_thesis_meta(self):
        decision = decide_publication_match(
            pmid_match_id=50,
            thesis_meta_match_id=40,
        )
        assert decision == PublicationMatchDecision(
            action="match", publication_id=50, matched_by=DeduplicationKey.PMID
        )

    def test_thesis_meta_only(self):
        decision = decide_publication_match(thesis_meta_match_id=40)
        assert decision == PublicationMatchDecision(
            action="match",
            publication_id=40,
            matched_by=DeduplicationKey.THESIS_META,
        )
