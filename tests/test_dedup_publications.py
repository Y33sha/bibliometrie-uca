"""Tests d'intégration — déduplication des publications.

Teste la logique de find_or_create dans services/publications.py
avec une vraie base PostgreSQL (bibliometrie_test).
Chaque test tourne dans une transaction rollbackée (isolation complète).
"""

import pytest
from services.publications import find_or_create, find_by_doi


# ── Helpers ──────────────────────────────────────────────────────

def _create(db, **kwargs):
    """Crée une publication via find_or_create et retourne (id, is_new)."""
    defaults = {
        "title": "Test Publication",
        "title_normalized": "test publication",
        "pub_year": 2024,
        "doc_type": "article",
        "doi": None,
        "oa_status": "unknown",
        "journal_id": None,
    }
    defaults.update(kwargs)
    return find_or_create(db, **defaults)


def _create_journal(db, title="Test Journal"):
    """Crée un journal minimal et retourne son id."""
    from utils.normalize import normalize_text
    db.execute(
        "INSERT INTO journals (title, title_normalized) VALUES (%s, %s) RETURNING id",
        (title, normalize_text(title))
    )
    return db.fetchone()["id"]


# ── Même DOI → fusion ───────────────────────────────────────────

class TestDedupByDoi:
    def test_same_doi_same_type_merges(self, db):
        """Même DOI, même type → retrouve la même publication."""
        id1, new1 = _create(db, doi="10.1234/test", title="Article A",
                            title_normalized="article a")
        id2, new2 = _create(db, doi="10.1234/test", title="Article A (bis)",
                            title_normalized="article a bis")

        assert new1 is True
        assert new2 is False
        assert id1 == id2

    def test_doi_case_insensitive(self, db):
        """DOI case-insensitive → fusion."""
        id1, _ = _create(db, doi="10.1234/ABC")
        id2, new2 = _create(db, doi="10.1234/abc")

        assert id1 == id2
        assert new2 is False

    def test_different_doi_creates_new(self, db):
        """DOI différents → deux publications distinctes."""
        id1, _ = _create(db, doi="10.1234/aaa")
        id2, _ = _create(db, doi="10.1234/bbb")

        assert id1 != id2


# ── DOI + types incompatibles ────────────────────────────────────

class TestDedupDoiTypeConflict:
    def test_chapter_vs_book_no_merge(self, db):
        """Même DOI, chapitre vs ouvrage → pas de fusion (DOI = celui de l'ouvrage)."""
        id_book, _ = _create(db, doi="10.1234/book", doc_type="book",
                             title="The Book", title_normalized="the book")
        id_chap, new = _create(db, doi="10.1234/book", doc_type="book_chapter",
                               title="Chapter 1", title_normalized="chapter 1")

        assert id_book != id_chap
        assert new is True

        # Le chapitre ne doit pas avoir hérité du DOI de l'ouvrage
        db.execute("SELECT doi FROM publications WHERE id = %s", (id_chap,))
        assert db.fetchone()["doi"] is None

    def test_book_vs_chapter_no_merge(self, db):
        """Même DOI, ouvrage après chapitre → pas de fusion, DOI retiré du chapitre."""
        id_chap, _ = _create(db, doi="10.1234/book", doc_type="book_chapter",
                             title="Chapter 1", title_normalized="chapter 1")
        id_book, _ = _create(db, doi="10.1234/book", doc_type="book",
                             title="The Book", title_normalized="the book")

        assert id_chap != id_book

        # Le DOI doit avoir été retiré du chapitre
        db.execute("SELECT doi FROM publications WHERE id = %s", (id_chap,))
        assert db.fetchone()["doi"] is None

    def test_two_chapters_same_doi_different_title(self, db):
        """Deux chapitres avec même DOI mais titres différents → pas de fusion, DOI retiré."""
        id1, _ = _create(db, doi="10.1234/book", doc_type="book_chapter",
                         title="Chapter 1", title_normalized="chapter 1")
        id2, _ = _create(db, doi="10.1234/book", doc_type="book_chapter",
                         title="Chapter 2", title_normalized="chapter 2")

        assert id1 != id2

        # DOI retiré des deux
        db.execute("SELECT doi FROM publications WHERE id = %s", (id1,))
        assert db.fetchone()["doi"] is None
        db.execute("SELECT doi FROM publications WHERE id = %s", (id2,))
        assert db.fetchone()["doi"] is None

    def test_two_chapters_same_doi_same_title(self, db):
        """Deux chapitres avec même DOI et même titre → fusion."""
        id1, _ = _create(db, doi="10.1234/chap", doc_type="book_chapter",
                         title="Chapter 1", title_normalized="chapter 1")
        id2, new = _create(db, doi="10.1234/chap", doc_type="book_chapter",
                           title="Chapter 1", title_normalized="chapter 1")

        assert id1 == id2
        assert new is False


# ── Déduplication par titre + année + journal ────────────────────

class TestDedupByTitle:
    def test_same_title_year_journal_merges(self, db):
        """Même titre normalisé + année + journal → fusion (articles)."""
        jid = _create_journal(db)
        id1, _ = _create(db, title="Mon Article", title_normalized="mon article",
                         pub_year=2024, journal_id=jid, doc_type="article")
        id2, new = _create(db, title="Mon Article (v2)", title_normalized="mon article",
                           pub_year=2024, journal_id=jid, doc_type="article")

        assert id1 == id2
        assert new is False

    def test_same_title_different_year_no_merge(self, db):
        """Même titre + journal mais année différente → pas de fusion."""
        jid = _create_journal(db)
        id1, _ = _create(db, title_normalized="mon article",
                         pub_year=2023, journal_id=jid, doc_type="article")
        id2, _ = _create(db, title_normalized="mon article",
                         pub_year=2024, journal_id=jid, doc_type="article")

        assert id1 != id2

    def test_same_title_different_journal_no_merge(self, db):
        """Même titre + année mais journal différent → pas de fusion."""
        j1 = _create_journal(db, "Journal A")
        j2 = _create_journal(db, "Journal B")
        id1, _ = _create(db, title_normalized="mon article",
                         pub_year=2024, journal_id=j1, doc_type="article")
        id2, _ = _create(db, title_normalized="mon article",
                         pub_year=2024, journal_id=j2, doc_type="article")

        assert id1 != id2

    def test_title_match_with_contradicting_doi_no_merge(self, db):
        """Même titre+année+journal mais DOI contradictoires → pas de fusion."""
        jid = _create_journal(db)
        id1, _ = _create(db, doi="10.1234/aaa", title_normalized="mon article",
                         pub_year=2024, journal_id=jid, doc_type="article")
        id2, _ = _create(db, doi="10.1234/bbb", title_normalized="mon article",
                         pub_year=2024, journal_id=jid, doc_type="article")

        assert id1 != id2

    def test_title_match_only_for_articles(self, db):
        """Le match par titre ne s'applique qu'aux articles (pas book_chapter, etc.)."""
        jid = _create_journal(db)
        id1, _ = _create(db, title_normalized="mon chapitre",
                         pub_year=2024, journal_id=jid, doc_type="book_chapter")
        id2, _ = _create(db, title_normalized="mon chapitre",
                         pub_year=2024, journal_id=jid, doc_type="book_chapter")

        assert id1 != id2

    def test_no_journal_no_title_match(self, db):
        """Sans journal_id, pas de match par titre (trop risqué)."""
        id1, _ = _create(db, title_normalized="mon article",
                         pub_year=2024, doc_type="article")
        id2, _ = _create(db, title_normalized="mon article",
                         pub_year=2024, doc_type="article")

        assert id1 != id2


# ── Pas de DOI → pas de faux positif ────────────────────────────

class TestNoDoi:
    def test_no_doi_no_journal_creates_separate(self, db):
        """Sans DOI ni journal, chaque appel crée une publication distincte."""
        id1, _ = _create(db, title="Article X", title_normalized="article x")
        id2, _ = _create(db, title="Article Y", title_normalized="article y")

        assert id1 != id2

    def test_no_doi_same_title_no_merge_without_journal(self, db):
        """Sans DOI, même titre mais sans journal → pas de fusion."""
        id1, _ = _create(db, title_normalized="article x", doc_type="article")
        id2, _ = _create(db, title_normalized="article x", doc_type="article")

        assert id1 != id2


# ── Enrichissement ───────────────────────────────────────────────

class TestEnrich:
    def test_doi_enriches_existing(self, db):
        """Une 2e source apporte un DOI à une publication qui n'en avait pas."""
        jid = _create_journal(db)
        id1, _ = _create(db, title_normalized="mon article",
                         pub_year=2024, journal_id=jid, doc_type="article")
        id2, _ = _create(db, doi="10.1234/new", title_normalized="mon article",
                         pub_year=2024, journal_id=jid, doc_type="article")

        assert id1 == id2
        db.execute("SELECT doi FROM publications WHERE id = %s", (id1,))
        assert db.fetchone()["doi"] == "10.1234/new"

    def test_oa_status_upgrade(self, db):
        """Le statut OA s'améliore (closed → green)."""
        id1, _ = _create(db, doi="10.1234/oa", oa_status="closed")
        _create(db, doi="10.1234/oa", oa_status="green")

        db.execute("SELECT oa_status FROM publications WHERE id = %s", (id1,))
        assert db.fetchone()["oa_status"] == "green"

    def test_diamond_always_wins(self, db):
        """Diamond prime sur tout."""
        id1, _ = _create(db, doi="10.1234/dia", oa_status="gold")
        _create(db, doi="10.1234/dia", oa_status="diamond")

        db.execute("SELECT oa_status FROM publications WHERE id = %s", (id1,))
        assert db.fetchone()["oa_status"] == "diamond"

    def test_allow_create_false(self, db):
        """allow_create=False → retourne None si non trouvée."""
        result, _ = find_or_create(db, title="X", title_normalized="x",
                                   pub_year=2024, allow_create=False)
        assert result is None
