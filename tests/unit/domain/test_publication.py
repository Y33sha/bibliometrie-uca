"""Tests des value objects et règles de domain/publication.py
(DOI, HALId, NNT, best_oa_status, resolve_doi_conflict,
clean_publication_title)."""

from dataclasses import FrozenInstanceError

import pytest

from domain.errors import ValidationError
from domain.publication import (
    DOI,
    NNT,
    OA_RANK,
    DoiConflictResolution,
    HALId,
    best_oa_status,
    clean_publication_title,
    resolve_doi_conflict,
)

# ── DOI ────────────────────────────────────────────────────────────


class TestDOIConstruction:
    def test_accepts_plain_doi(self):
        d = DOI("10.1234/test")
        assert d.value == "10.1234/test"
        assert str(d) == "10.1234/test"

    def test_strips_https_prefix(self):
        assert DOI("https://doi.org/10.1234/test").value == "10.1234/test"

    def test_strips_http_prefix(self):
        assert DOI("http://doi.org/10.1234/test").value == "10.1234/test"

    def test_strips_dx_prefix(self):
        assert DOI("https://dx.doi.org/10.1234/test").value == "10.1234/test"

    def test_strips_whitespace(self):
        assert DOI("  10.1234/test  ").value == "10.1234/test"

    def test_normalizes_version_suffix(self):
        assert DOI("10.6084/m9.figshare.31023197.v1").value == "10.6084/m9.figshare.31023197"
        assert DOI("10.36227/techrxiv.19754971.v2").value == "10.36227/techrxiv.19754971"

    def test_does_not_strip_v_not_followed_by_digit(self):
        """Un .v suivi de non-chiffre ne doit pas être strippé."""
        assert DOI("10.1234/journal.v12.issue3").value == "10.1234/journal.v12.issue3"

    def test_lowercases(self):
        """Le DOI complet est normalisé en minuscules (le standard CrossRef
        traite le DOI en case-insensitive ; lowercase évite les faux doublons
        cross-sources)."""
        assert DOI("10.1038/Nature").value == "10.1038/nature"
        assert DOI("10.1038/NATURE").value == "10.1038/nature"
        assert DOI("https://doi.org/10.1038/NATURE").value == "10.1038/nature"


class TestDOIInvalid:
    def test_raises_on_empty(self):
        with pytest.raises(ValidationError):
            DOI("")

    def test_raises_on_whitespace_only(self):
        with pytest.raises(ValidationError):
            DOI("   ")

    def test_raises_on_url_prefix_only(self):
        with pytest.raises(ValidationError):
            DOI("https://doi.org/")


class TestDOITryParse:
    def test_returns_none_on_none(self):
        assert DOI.try_parse(None) is None

    def test_returns_none_on_empty(self):
        assert DOI.try_parse("") is None

    def test_returns_none_on_whitespace(self):
        assert DOI.try_parse("   ") is None

    def test_returns_doi_on_valid(self):
        d = DOI.try_parse("10.1234/test")
        assert d is not None
        assert d.value == "10.1234/test"

    def test_normalizes_on_parse(self):
        d = DOI.try_parse("https://doi.org/10.1234/TEST.v3")
        assert d.value == "10.1234/test"


class TestDOIImmutable:
    def test_is_frozen(self):
        d = DOI("10.1234/test")
        with pytest.raises(FrozenInstanceError):
            d.value = "other"

    def test_is_hashable(self):
        """Deux DOI égaux doivent avoir le même hash (utilisable dans un set)."""
        a = DOI("10.1234/test")
        b = DOI("https://doi.org/10.1234/test")
        assert a == b
        assert hash(a) == hash(b)
        assert {a, b} == {a}

    def test_equality_by_normalized_value(self):
        """Deux DOI avec le même canon sont égaux même si écrits différemment."""
        assert DOI("10.1234/test") == DOI("  10.1234/test.v2  ")


# ── HALId ──────────────────────────────────────────────────────────


class TestHALIdConstruction:
    def test_accepts_plain_hal_id(self):
        assert HALId("hal-04123456").value == "hal-04123456"

    def test_accepts_other_portals(self):
        assert HALId("tel-02345678").value == "tel-02345678"
        assert HALId("halshs-01234567").value == "halshs-01234567"
        assert HALId("inserm-09876543").value == "inserm-09876543"
        assert HALId("pasteur-11111111").value == "pasteur-11111111"
        assert HALId("cea-22222222").value == "cea-22222222"
        assert HALId("ineris-33333333").value == "ineris-33333333"

    def test_strips_version_suffix(self):
        assert HALId("hal-04123456v2").value == "hal-04123456"

    def test_lowercases(self):
        assert HALId("HAL-04123456").value == "hal-04123456"

    def test_accepts_url(self):
        assert HALId("https://hal.science/hal-04123456").value == "hal-04123456"
        assert HALId("https://hal.science/hal-04123456v2").value == "hal-04123456"
        assert HALId("https://tel.archives-ouvertes.fr/tel-02345678").value == "tel-02345678"


class TestHALIdInvalid:
    def test_raises_on_empty(self):
        with pytest.raises(ValidationError):
            HALId("")

    def test_raises_on_unknown_prefix(self):
        with pytest.raises(ValidationError):
            HALId("other-12345")

    def test_raises_on_no_digits(self):
        with pytest.raises(ValidationError):
            HALId("hal-")


class TestHALIdTryParse:
    def test_none(self):
        assert HALId.try_parse(None) is None

    def test_invalid(self):
        assert HALId.try_parse("garbage") is None

    def test_valid(self):
        assert HALId.try_parse("https://hal.science/hal-04123456v1").value == "hal-04123456"


# ── NNT ────────────────────────────────────────────────────────────


class TestNNT:
    def test_uppercases(self):
        assert NNT("2021clfa0030").value == "2021CLFA0030"

    def test_strips_whitespace(self):
        assert NNT("  2021CLFA0030  ").value == "2021CLFA0030"

    def test_raises_on_empty(self):
        with pytest.raises(ValidationError):
            NNT("")

    def test_raises_on_whitespace(self):
        with pytest.raises(ValidationError):
            NNT("   ")

    def test_raises_on_non_alnum(self):
        with pytest.raises(ValidationError):
            NNT("2021-CLFA-0030")

    def test_try_parse_none(self):
        assert NNT.try_parse(None) is None

    def test_try_parse_invalid(self):
        assert NNT.try_parse("") is None


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
