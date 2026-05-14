"""Tests des règles de déduplication / création des publications."""

from domain.publications.deduplication import (
    DeduplicationKey,
    DoiAttributionDecision,
    DoiConflictResolution,
    MetadataDeduplicationCase,
    PublicationMatchDecision,
    decide_doi_attribution,
    decide_publication_match,
    resolve_doi_conflict,
)

# ── resolve_doi_conflict (règle pure) ──────────────────────────────


class TestResolveDoiConflictPure:
    def test_chapter_vs_book_drops_doi(self):
        """Chapitre avec DOI qui pointe vers livre : DOI retiré du chapitre."""
        res = resolve_doi_conflict(
            new_doi="10.x/book",
            new_doc_type="book_chapter",
            new_title_normalized="chapitre",
            existing_doc_type="book",
            existing_title_normalized="livre",
            existing_id=1,
        )
        assert res == DoiConflictResolution(
            accepted_doi=None, merge_with_id=None, clear_existing_doi=False
        )

    def test_book_vs_chapter_strips_doi_from_chapter(self):
        """Livre avec DOI existant sur un chapitre : chapitre perd son DOI, livre garde."""
        res = resolve_doi_conflict(
            new_doi="10.x/book",
            new_doc_type="book",
            new_title_normalized="livre",
            existing_doc_type="book_chapter",
            existing_title_normalized="chapitre",
            existing_id=42,
        )
        assert res == DoiConflictResolution(
            accepted_doi="10.x/book", merge_with_id=None, clear_existing_doi=True
        )

    def test_two_chapters_different_titles_strip_both(self):
        res = resolve_doi_conflict(
            new_doi="10.x/shared",
            new_doc_type="book_chapter",
            new_title_normalized="c2",
            existing_doc_type="book_chapter",
            existing_title_normalized="c1",
            existing_id=7,
        )
        assert res == DoiConflictResolution(
            accepted_doi=None, merge_with_id=None, clear_existing_doi=True
        )

    def test_two_chapters_same_title_merges(self):
        res = resolve_doi_conflict(
            new_doi="10.x/shared",
            new_doc_type="book_chapter",
            new_title_normalized="same",
            existing_doc_type="book_chapter",
            existing_title_normalized="same",
            existing_id=42,
        )
        assert res == DoiConflictResolution(
            accepted_doi="10.x/shared", merge_with_id=42, clear_existing_doi=False
        )

    def test_compatible_types_merge(self):
        res = resolve_doi_conflict(
            new_doi="10.x/a",
            new_doc_type="article",
            new_title_normalized="a",
            existing_doc_type="article",
            existing_title_normalized="a",
            existing_id=42,
        )
        assert res == DoiConflictResolution(
            accepted_doi="10.x/a", merge_with_id=42, clear_existing_doi=False
        )

    def test_existing_doc_type_none_is_compatible(self):
        """Pas de doc_type existant → pas de cas spécial, on fusionne."""
        res = resolve_doi_conflict(
            new_doi="10.x/a",
            new_doc_type="article",
            new_title_normalized="a",
            existing_doc_type=None,
            existing_title_normalized="a",
            existing_id=1,
        )
        assert res.accepted_doi == "10.x/a"
        assert res.merge_with_id == 1
        assert res.clear_existing_doi is False

    def test_chapter_variants_recognized(self):
        """Les alias book-chapter et chapter sont traités comme book_chapter."""
        for alias in ("book-chapter", "chapter"):
            res = resolve_doi_conflict(
                new_doi="10.x/b",
                new_doc_type=alias,
                new_title_normalized="c",
                existing_doc_type="book",
                existing_title_normalized="livre",
                existing_id=1,
            )
            assert res.accepted_doi is None, f"alias {alias} non reconnu"


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
            metadata_match=(40, MetadataDeduplicationCase.THESIS_TITLE_YEAR),
        )
        assert decision == PublicationMatchDecision(
            action="match", publication_id=10, matched_by=DeduplicationKey.DOI
        )

    def test_nnt_wins_over_hal_and_metadata(self):
        decision = decide_publication_match(
            nnt_match_id=20,
            hal_id_match_id=30,
            metadata_match=(40, MetadataDeduplicationCase.THESIS_TITLE_YEAR),
        )
        assert decision == PublicationMatchDecision(
            action="match", publication_id=20, matched_by=DeduplicationKey.NNT
        )

    def test_hal_wins_over_metadata(self):
        decision = decide_publication_match(
            hal_id_match_id=30,
            metadata_match=(40, MetadataDeduplicationCase.THESIS_TITLE_YEAR),
        )
        assert decision == PublicationMatchDecision(
            action="match", publication_id=30, matched_by=DeduplicationKey.HAL_ID
        )

    def test_metadata_only(self):
        decision = decide_publication_match(
            metadata_match=(40, MetadataDeduplicationCase.THESIS_TITLE_YEAR),
        )
        assert decision == PublicationMatchDecision(
            action="match",
            publication_id=40,
            matched_by=MetadataDeduplicationCase.THESIS_TITLE_YEAR,
        )


# ── decide_doi_attribution (règle pure) ────────────────────────────


class TestDecideDoiAttribution:
    def test_no_proposed_doi_is_noop(self):
        decision = decide_doi_attribution(
            current_doi=None,
            proposed_doi=None,
            current_pub_id=1,
            existing_doi_match_id=None,
        )
        assert decision == DoiAttributionDecision(action="noop")

    def test_empty_proposed_doi_is_noop(self):
        decision = decide_doi_attribution(
            current_doi=None,
            proposed_doi="",
            current_pub_id=1,
            existing_doi_match_id=None,
        )
        assert decision == DoiAttributionDecision(action="noop")

    def test_current_doi_present_is_noop_even_when_proposed_is_free(self):
        """Politique conservative : on n'écrase jamais un DOI existant."""
        decision = decide_doi_attribution(
            current_doi="10.x/already",
            proposed_doi="10.x/proposed",
            current_pub_id=1,
            existing_doi_match_id=None,
        )
        assert decision == DoiAttributionDecision(action="noop")

    def test_current_doi_same_as_proposed_is_noop(self):
        """Même DOI déjà en place : noop, pas attribute (effet identique mais label honnête)."""
        decision = decide_doi_attribution(
            current_doi="10.x/same",
            proposed_doi="10.x/same",
            current_pub_id=1,
            existing_doi_match_id=1,
        )
        assert decision == DoiAttributionDecision(action="noop")

    def test_doi_held_by_other_pub_merges(self):
        decision = decide_doi_attribution(
            current_doi=None,
            proposed_doi="10.x/held",
            current_pub_id=1,
            existing_doi_match_id=42,
        )
        assert decision == DoiAttributionDecision(action="merge", merge_with_id=42)

    def test_doi_free_attributes(self):
        decision = decide_doi_attribution(
            current_doi=None,
            proposed_doi="10.x/free",
            current_pub_id=1,
            existing_doi_match_id=None,
        )
        assert decision == DoiAttributionDecision(action="attribute")

    def test_doi_already_on_current_pub_attributes(self):
        """Cas idempotent : le DOI proposé est déjà sur la pub courante (current_doi serait alors non-None, donc en réalité ce cas tombe sur le noop).

        Ce test garde le cas de figure où current_doi serait None mais existing_doi_match_id == current_pub_id (incohérence théorique : signifie que find_by_doi a retourné la pub courante alors que sa colonne doi est nulle — ne devrait pas arriver, mais la règle décide quand même = attribute).
        """
        decision = decide_doi_attribution(
            current_doi=None,
            proposed_doi="10.x/x",
            current_pub_id=1,
            existing_doi_match_id=1,
        )
        assert decision == DoiAttributionDecision(action="attribute")
