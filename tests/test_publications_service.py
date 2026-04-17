"""Tests de caractérisation pour services/publications.py.

Couvre les find_by_* (guards + happy path), try_merge_by_doi,
resolve_doi_conflict (chapter/book), update_oa_status/countries,
merge_publications. find_or_create est déjà couvert par test_integration.py.
"""

from services.publications import (
    find_by_doi,
    find_by_nnt,
    find_by_title,
    find_thesis_by_title,
    merge_publications,
    resolve_doi_conflict,
    try_merge_by_doi,
    update_countries,
    update_oa_status,
)


# ── Helpers ────────────────────────────────────────────────────────

def _insert_journal(db, title="Nature"):
    db.execute(
        "INSERT INTO journals (title, title_normalized) VALUES (%s, lower(%s)) RETURNING id",
        (title, title),
    )
    return db.fetchone()["id"]


def _insert_publication(db, title="Test", pub_year=2024, doi=None,
                       doc_type="article", journal_id=None,
                       oa_status="unknown"):
    db.execute(
        """
        INSERT INTO publications (title, title_normalized, pub_year, doi,
                                  doc_type, journal_id, oa_status)
        VALUES (%s, lower(%s), %s, %s, %s::doc_type, %s, %s::oa_type)
        RETURNING id
        """,
        (title, title, pub_year, doi, doc_type, journal_id, oa_status),
    )
    return db.fetchone()["id"]


def _insert_source_publication(db, publication_id, source="hal", source_id="h-1",
                              title="Test", external_ids=None):
    import json
    db.execute(
        """
        INSERT INTO source_publications (source, source_id, title,
                                         publication_id, external_ids)
        VALUES (%s, %s, %s, %s, %s::jsonb)
        RETURNING id
        """,
        (source, source_id, title, publication_id,
         json.dumps(external_ids) if external_ids else None),
    )
    return db.fetchone()["id"]


def _insert_person(db, last="Dupont", first="Jean"):
    db.execute(
        """
        INSERT INTO persons (last_name, first_name,
                             last_name_normalized, first_name_normalized)
        VALUES (%s, %s, lower(%s), lower(%s)) RETURNING id
        """,
        (last, first, last, first),
    )
    return db.fetchone()["id"]


def _insert_authorship(db, publication_id, person_id=None):
    db.execute(
        "INSERT INTO authorships (publication_id, person_id) VALUES (%s, %s) RETURNING id",
        (publication_id, person_id),
    )
    return db.fetchone()["id"]


# ── find_by_* ──────────────────────────────────────────────────────

class TestFindByDoi:
    def test_returns_none_on_empty(self, db):
        assert find_by_doi(db, None) is None
        assert find_by_doi(db, "") is None

    def test_finds_by_doi_case_insensitive(self, db):
        pub_id = _insert_publication(db, doi="10.1234/ABC")
        result = find_by_doi(db, "10.1234/abc")
        assert result is not None
        assert result.id == pub_id

    def test_returns_none_if_not_found(self, db):
        assert find_by_doi(db, "10.1234/unknown") is None


class TestFindByNnt:
    def test_returns_none_on_empty(self, db):
        assert find_by_nnt(db, None) is None
        assert find_by_nnt(db, "") is None

    def test_finds_by_nnt_in_external_ids(self, db):
        pub_id = _insert_publication(db, doc_type="thesis")
        _insert_source_publication(
            db, pub_id, source="theses", source_id="t-1",
            external_ids={"nnt": "2024UCAC0001"},
        )
        result = find_by_nnt(db, "2024UCAC0001")
        assert result is not None
        assert result.id == pub_id

    def test_nnt_uppercased_for_lookup(self, db):
        pub_id = _insert_publication(db, doc_type="thesis")
        _insert_source_publication(
            db, pub_id, source="theses", source_id="t-1",
            external_ids={"nnt": "2024UCAC0001"},
        )
        # Même en minuscules en entrée, trouve
        result = find_by_nnt(db, "2024ucac0001")
        assert result is not None


class TestFindByTitle:
    def test_returns_none_on_missing_input(self, db):
        assert find_by_title(db, "", 2024, 1) is None
        assert find_by_title(db, "title", 2024, None) is None

    def test_finds_by_title_year_journal(self, db):
        j_id = _insert_journal(db)
        pub_id = _insert_publication(db, title="My Paper", journal_id=j_id)
        result = find_by_title(db, "my paper", 2024, j_id)
        assert result is not None
        assert result.id == pub_id

    def test_not_found_if_year_differs(self, db):
        j_id = _insert_journal(db)
        _insert_publication(db, title="X", pub_year=2023, journal_id=j_id)
        assert find_by_title(db, "x", 2024, j_id) is None


class TestFindThesisByTitle:
    def test_returns_empty_on_missing_input(self, db):
        assert find_thesis_by_title(db, "", 2024) == []
        assert find_thesis_by_title(db, "t", None) == []

    def test_finds_only_theses(self, db):
        """Ne retourne que les thèses."""
        _insert_publication(db, title="A", pub_year=2024, doc_type="article")
        t_id = _insert_publication(db, title="A", pub_year=2024, doc_type="thesis")
        result = find_thesis_by_title(db, "a", 2024)
        assert [r.id for r in result] == [t_id]

    def test_returns_multiple_candidates(self, db):
        t1 = _insert_publication(db, title="Dup", pub_year=2024, doc_type="thesis")
        t2 = _insert_publication(db, title="Dup", pub_year=2024, doc_type="thesis")
        result = find_thesis_by_title(db, "dup", 2024)
        assert {r.id for r in result} == {t1, t2}


# ── try_merge_by_doi ───────────────────────────────────────────────

class TestTryMergeByDoi:
    def test_noop_if_no_doi_given(self, db):
        pub_id = _insert_publication(db)
        assert try_merge_by_doi(db, pub_id, None) == pub_id

    def test_noop_if_pub_already_has_doi(self, db):
        pub_id = _insert_publication(db, doi="10.1234/existing")
        assert try_merge_by_doi(db, pub_id, "10.1234/other") == pub_id

    def test_assigns_doi_if_pub_has_none(self, db):
        pub_id = _insert_publication(db, doi=None)
        assert try_merge_by_doi(db, pub_id, "10.1234/new") == pub_id
        db.execute("SELECT doi FROM publications WHERE id = %s", (pub_id,))
        assert db.fetchone()["doi"] == "10.1234/new"

    def test_merges_into_existing_pub_with_same_doi(self, db):
        existing = _insert_publication(db, title="Existing", doi="10.1234/shared")
        new_pub = _insert_publication(db, title="New", doi=None)

        result = try_merge_by_doi(db, new_pub, "10.1234/shared")

        assert result == existing  # pub id de la cible
        db.execute("SELECT id FROM publications WHERE id = %s", (new_pub,))
        assert db.fetchone() is None  # new_pub supprimée (fusionnée)


# ── resolve_doi_conflict ───────────────────────────────────────────

class TestResolveDoiConflict:
    def test_chapter_vs_existing_book_drops_doi(self, db):
        """Chapitre avec DOI qui pointe vers livre : DOI retiré du chapitre."""
        from services.publications import PubByDoi
        existing = PubByDoi(id=1, doc_type="book", title_normalized="livre")

        doi, merge_id = resolve_doi_conflict(db, "10.x/book", "book_chapter",
                                             "chapitre", existing)
        assert doi is None
        assert merge_id is None

    def test_book_vs_existing_chapter_strips_doi_from_chapter(self, db):
        """Livre avec DOI existant sur un chapitre : DOI retiré du chapitre, livre garde."""
        from services.publications import PubByDoi
        existing_id = _insert_publication(
            db, title="Chapitre", doc_type="book_chapter", doi="10.x/book"
        )
        existing = PubByDoi(id=existing_id, doc_type="book_chapter",
                            title_normalized="chapitre")

        doi, merge_id = resolve_doi_conflict(db, "10.x/book", "book", "livre", existing)
        assert doi == "10.x/book"
        assert merge_id is None
        db.execute("SELECT doi FROM publications WHERE id = %s", (existing_id,))
        assert db.fetchone()["doi"] is None

    def test_two_chapters_different_titles_strip_both(self, db):
        """2 chapitres avec titres différents partageant un DOI : les 2 perdent le DOI."""
        from services.publications import PubByDoi
        existing_id = _insert_publication(
            db, title="C1", doc_type="book_chapter", doi="10.x/shared"
        )
        existing = PubByDoi(id=existing_id, doc_type="book_chapter", title_normalized="c1")

        doi, merge_id = resolve_doi_conflict(db, "10.x/shared", "book_chapter",
                                             "c2_different", existing)
        assert doi is None
        assert merge_id is None
        db.execute("SELECT doi FROM publications WHERE id = %s", (existing_id,))
        assert db.fetchone()["doi"] is None

    def test_two_chapters_same_title_merges(self, db):
        """2 chapitres avec même titre + DOI → fusion."""
        from services.publications import PubByDoi
        existing = PubByDoi(id=42, doc_type="book_chapter", title_normalized="same")

        doi, merge_id = resolve_doi_conflict(db, "10.x/shared", "book_chapter",
                                             "same", existing)
        assert doi == "10.x/shared"
        assert merge_id == 42

    def test_compatible_types_merge(self, db):
        """Types compatibles (ex: 2 articles) → fusion normale."""
        from services.publications import PubByDoi
        existing = PubByDoi(id=42, doc_type="article", title_normalized="a")
        doi, merge_id = resolve_doi_conflict(db, "10.x/a", "article", "a", existing)
        assert doi == "10.x/a"
        assert merge_id == 42


# ── update_oa_status / update_countries ────────────────────────────

class TestUpdateOaStatus:
    def test_updates(self, db):
        pub_id = _insert_publication(db, oa_status="unknown")
        update_oa_status(db, pub_id, "gold")
        db.execute("SELECT oa_status FROM publications WHERE id = %s", (pub_id,))
        assert db.fetchone()["oa_status"] == "gold"


class TestUpdateCountries:
    def test_updates(self, db):
        pub_id = _insert_publication(db)
        update_countries(db, pub_id, ["FR", "US"])
        db.execute("SELECT countries FROM publications WHERE id = %s", (pub_id,))
        assert db.fetchone()["countries"] == ["FR", "US"]


# ── merge_publications ────────────────────────────────────────────

class TestMergePublications:
    def test_transfers_source_publications_and_authorships(self, db):
        target = _insert_publication(db, title="Target")
        source = _insert_publication(db, title="Source")
        sp_id = _insert_source_publication(db, source, source="hal", source_id="h-src")

        person_id = _insert_person(db)
        auth_id = _insert_authorship(db, source, person_id=person_id)

        merge_publications(db, target, source)

        # source_publication repointée
        db.execute("SELECT publication_id FROM source_publications WHERE id = %s", (sp_id,))
        assert db.fetchone()["publication_id"] == target
        # authorship repointée
        db.execute("SELECT publication_id FROM authorships WHERE id = %s", (auth_id,))
        assert db.fetchone()["publication_id"] == target
        # source supprimée
        db.execute("SELECT id FROM publications WHERE id = %s", (source,))
        assert db.fetchone() is None

    def test_dedup_authorships_by_person(self, db):
        """Si target et source ont une authorship pour la même person, la source est jetée."""
        target = _insert_publication(db, title="Target")
        source = _insert_publication(db, title="Source")
        person_id = _insert_person(db)
        keep_auth = _insert_authorship(db, target, person_id=person_id)
        drop_auth = _insert_authorship(db, source, person_id=person_id)

        merge_publications(db, target, source)

        db.execute("SELECT id FROM authorships WHERE id = %s", (keep_auth,))
        assert db.fetchone() is not None
        db.execute("SELECT id FROM authorships WHERE id = %s", (drop_auth,))
        assert db.fetchone() is None

    def test_enriches_journal_id(self, db):
        """Target sans journal_id → reçoit celui de la source (COALESCE)."""
        j_id = _insert_journal(db)
        target = _insert_publication(db, title="Target", doi=None, journal_id=None)
        source = _insert_publication(db, title="Source", doi=None, journal_id=j_id)

        merge_publications(db, target, source)

        db.execute("SELECT journal_id FROM publications WHERE id = %s", (target,))
        assert db.fetchone()["journal_id"] == j_id

    def test_doi_transferred_when_target_has_none(self, db):
        """Target sans DOI, source avec : la cible reçoit le DOI de la source."""
        target = _insert_publication(db, title="Target", doi=None)
        source = _insert_publication(db, title="Source", doi="10.1234/src")

        merge_publications(db, target, source)

        db.execute("SELECT doi FROM publications WHERE id = %s", (target,))
        assert db.fetchone()["doi"] == "10.1234/src"

    def test_keeps_target_doi_when_both_set(self, db):
        """Si les deux ont un DOI, celui de la cible est conservé."""
        target = _insert_publication(db, title="Target", doi="10.1234/target")
        source = _insert_publication(db, title="Source", doi="10.1234/source")

        merge_publications(db, target, source)

        db.execute("SELECT doi FROM publications WHERE id = %s", (target,))
        assert db.fetchone()["doi"] == "10.1234/target"

    def test_oa_status_upgrade_diamond_wins(self, db):
        """Si source est diamond, la cible devient diamond même si elle avait gold."""
        target = _insert_publication(db, title="Target", oa_status="gold")
        source = _insert_publication(db, title="Source", oa_status="diamond")
        merge_publications(db, target, source)
        db.execute("SELECT oa_status FROM publications WHERE id = %s", (target,))
        assert db.fetchone()["oa_status"] == "diamond"

    def test_oa_status_upgrade_from_closed_to_gold(self, db):
        target = _insert_publication(db, title="Target", oa_status="closed")
        source = _insert_publication(db, title="Source", oa_status="gold")
        merge_publications(db, target, source)
        db.execute("SELECT oa_status FROM publications WHERE id = %s", (target,))
        assert db.fetchone()["oa_status"] == "gold"
