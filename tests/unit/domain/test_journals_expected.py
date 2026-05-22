"""Tests des règles d'attendus journal ↔ publication.

Cf. ``domain/journals/expected.py``.
"""

from domain.journals.expected import (
    EXPECTED_DOC_TYPES_BY_JOURNAL_TYPE,
    EXPECTED_OA_STATUSES_BY_OA_MODEL,
    is_doc_type_expected,
    is_oa_status_expected,
)


class TestIsOaStatusExpected:
    def test_subscription_closed_is_expected(self):
        assert is_oa_status_expected("subscription", "closed")

    def test_subscription_green_is_expected(self):
        assert is_oa_status_expected("subscription", "green")

    def test_subscription_gold_is_unexpected(self):
        assert not is_oa_status_expected("subscription", "gold")

    def test_subscription_diamond_is_unexpected(self):
        assert not is_oa_status_expected("subscription", "diamond")

    def test_full_oa_gold_is_expected(self):
        assert is_oa_status_expected("full_oa", "gold")

    def test_full_oa_diamond_is_expected(self):
        assert is_oa_status_expected("full_oa", "diamond")

    def test_full_oa_closed_is_unexpected(self):
        assert not is_oa_status_expected("full_oa", "closed")

    def test_full_oa_subscription_status_is_unexpected(self):
        assert not is_oa_status_expected("full_oa", "hybrid")

    def test_unknown_status_is_expected_regardless_of_model(self):
        # `unknown` = absence de signal, ne doit pas générer de warning.
        assert is_oa_status_expected("subscription", "unknown")
        assert is_oa_status_expected("full_oa", "unknown")

    def test_null_oa_model_is_expected(self):
        # Pas de signal côté revue → on ne flagge rien.
        assert is_oa_status_expected(None, "gold")
        assert is_oa_status_expected(None, "closed")

    def test_null_oa_status_is_expected(self):
        assert is_oa_status_expected("subscription", None)
        assert is_oa_status_expected("full_oa", None)

    def test_unknown_oa_model_is_expected(self):
        # oa_model libre (texte non normalisé) sans mapping → on ne flagge rien.
        assert is_oa_status_expected("custom_unmapped_model", "gold")


class TestIsDocTypeExpected:
    def test_journal_article_is_expected(self):
        assert is_doc_type_expected("journal", "article")

    def test_journal_review_is_expected(self):
        assert is_doc_type_expected("journal", "review")

    def test_journal_conference_paper_is_unexpected(self):
        assert not is_doc_type_expected("journal", "conference_paper")

    def test_journal_thesis_is_unexpected(self):
        assert not is_doc_type_expected("journal", "thesis")

    def test_proceedings_conference_paper_is_expected(self):
        assert is_doc_type_expected("proceedings", "conference_paper")

    def test_proceedings_article_is_unexpected(self):
        assert not is_doc_type_expected("proceedings", "article")

    def test_book_series_book_chapter_is_expected(self):
        assert is_doc_type_expected("book_series", "book_chapter")

    def test_preprint_server_preprint_is_expected(self):
        assert is_doc_type_expected("preprint_server", "preprint")

    def test_preprint_server_article_is_unexpected(self):
        assert not is_doc_type_expected("preprint_server", "article")

    def test_repository_accepts_anything(self):
        # Pour un repository, on n'a pas d'attendu strict.
        for doc_type in (
            "article",
            "preprint",
            "thesis",
            "dataset",
            "software",
            "book_chapter",
        ):
            assert is_doc_type_expected("repository", doc_type), doc_type

    def test_null_journal_type_is_expected(self):
        assert is_doc_type_expected(None, "article")

    def test_null_doc_type_is_expected(self):
        assert is_doc_type_expected("journal", None)


class TestMappingCoverage:
    """Garde-fou : les keys des mappings correspondent à des journal_type /
    oa_model réellement utilisés en base. Ce test verrouille la cohérence
    avec les valeurs côté schéma sans pour autant exiger d'exhaustivité —
    une nouvelle valeur en base ne devra pas être ajoutée silencieusement
    aux mappings."""

    def test_oa_model_keys_documented(self):
        # Les 3 oa_model en base à date.
        assert set(EXPECTED_OA_STATUSES_BY_OA_MODEL) == {
            "subscription",
            "full_oa",
            "repository",
        }

    def test_journal_type_keys_documented(self):
        # Les 6 valeurs de l'enum journal_type.
        assert set(EXPECTED_DOC_TYPES_BY_JOURNAL_TYPE) == {
            "journal",
            "proceedings",
            "book_series",
            "preprint_server",
            "repository",
            "media",
        }
