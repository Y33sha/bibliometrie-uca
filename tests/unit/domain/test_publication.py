"""Tests des règles métier de domain/publication.py
(best_oa_status, resolve_doi_conflict, clean_publication_title).

Les tests des VOs DOI/HALId/NNT vivent dans
``tests/unit/domain/publications/test_identifiers.py``.
"""

from domain.publication import (
    OA_RANK,
    DoiConflictResolution,
    best_oa_status,
    clean_publication_title,
    resolve_doi_conflict,
)

# ── Règles d'agrégation multi-sources ──────────────────────────────


class TestBestOAStatus:
    def test_returns_most_open(self):
        assert best_oa_status(["green", "gold", "closed"]) == "gold"

    def test_diamond_wins_over_gold(self):
        assert best_oa_status(["gold", "diamond"]) == "diamond"

    def test_ignores_none_and_empty(self):
        assert best_oa_status([None, "", "bronze"]) == "bronze"

    def test_returns_none_if_no_known_status(self):
        assert best_oa_status([None, None]) is None
        assert best_oa_status([]) is None

    def test_ignores_unknown_status_value(self):
        # un statut absent de OA_RANK est ignoré (rank=0), on garde l'autre
        assert best_oa_status(["mystery", "green"]) == "green"

    def test_unknown_kept_only_if_nothing_better(self):
        # le statut "unknown" a un rank > 0 : il gagne face à rien
        assert best_oa_status(["unknown"]) == "unknown"

    def test_rank_order_is_strict(self):
        # ordre documenté dans la docstring
        assert OA_RANK["diamond"] > OA_RANK["gold"] > OA_RANK["hybrid"]
        assert OA_RANK["hybrid"] > OA_RANK["bronze"] > OA_RANK["green"]
        assert OA_RANK["green"] > OA_RANK["closed"] > OA_RANK["unknown"]


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


# ── clean_publication_title (décodage double-encodage HTML) ────────


class TestCleanPublicationTitle:
    def test_decodes_double_encoded_html_tags(self):
        """Cas observé OpenAlex / ScanR : <i>...</i> arrive double-échappé."""
        result = clean_publication_title(
            "Detection of &amp;lt;i&amp;gt;Candida&amp;lt;/i&amp;gt; species"
        )
        assert result == "Detection of <i>Candida</i> species"

    def test_decodes_double_encoded_numeric_entities(self):
        """Entités numériques double-encodées (ex: &amp;#233; → é)."""
        assert clean_publication_title("Gagn&amp;#233; et al.") == "Gagné et al."

    def test_decodes_double_encoded_hex_entities(self):
        """Entités hexadécimales double-encodées (ex: &amp;#xE9; → é)."""
        assert clean_publication_title("Gagn&amp;#xE9; et al.") == "Gagné et al."

    def test_preserves_legitimate_single_amp(self):
        """Un &amp; isolé (encodage simple légitime) ne doit pas être touché —
        sinon on sur-décode "Smith & Jones" et on casse l'affichage."""
        assert clean_publication_title("Smith &amp; Jones") == "Smith &amp; Jones"

    def test_preserves_plain_text(self):
        assert clean_publication_title("Plain title without entities") == (
            "Plain title without entities"
        )

    def test_preserves_already_decoded_html(self):
        """Un titre avec balises HTML déjà propres est laissé tel quel."""
        assert clean_publication_title("<i>Candida</i> species") == ("<i>Candida</i> species")

    def test_idempotent(self):
        """Appliquer deux fois ne change rien (sécurité re-traitement)."""
        once = clean_publication_title("&amp;lt;i&amp;gt;Candida&amp;lt;/i&amp;gt;")
        twice = clean_publication_title(once)
        assert once == twice == "<i>Candida</i>"

    def test_returns_none_for_none(self):
        assert clean_publication_title(None) is None

    def test_returns_empty_for_empty(self):
        assert clean_publication_title("") == ""
