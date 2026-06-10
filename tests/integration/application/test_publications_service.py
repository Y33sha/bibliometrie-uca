"""Tests de caractérisation pour services/publications.py.

Couvre les find_by_* (guards + happy path), resolve_doi_conflict (chapter/book),
merge_publications.
"""

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.repositories.publication_repository import PubByDoi
from application.publications import (
    find_by_doi,
    find_by_nnt,
    find_thesis_by_title,
    mark_distinct,
    merge_publications,
    resolve_doi_conflict,
)
from domain.errors import DistinctDoiError
from infrastructure.repositories import publication_repository


@pytest.fixture
def repo(sa_sync_conn):
    return publication_repository(sa_sync_conn)


# ── Helpers ────────────────────────────────────────────────────────


def _insert_journal(conn, title="Nature"):
    return conn.execute(
        text("INSERT INTO journals (title, title_normalized) VALUES (:t, lower(:t)) RETURNING id"),
        {"t": title},
    ).scalar_one()


def _insert_publication(
    conn,
    title="Test",
    pub_year=2024,
    doi=None,
    doc_type="article",
    journal_id=None,
    oa_status="unknown",
):
    return conn.execute(
        text(
            """
            INSERT INTO publications (title, title_normalized, pub_year, doi,
                                      doc_type, journal_id, oa_status)
            VALUES (:title, lower(:title), :pub_year, :doi,
                    CAST(:doc_type AS doc_type), :journal_id, CAST(:oa_status AS oa_type))
            RETURNING id
            """
        ),
        {
            "title": title,
            "pub_year": pub_year,
            "doi": doi,
            "doc_type": doc_type,
            "journal_id": journal_id,
            "oa_status": oa_status,
        },
    ).scalar_one()


_INSERT_SOURCE_PUB_SQL = text(
    """
    INSERT INTO source_publications (source, source_id, title,
                                     publication_id, external_ids)
    VALUES (:source, :source_id, :title, :publication_id, :external_ids)
    RETURNING id
    """
).bindparams(bindparam("external_ids", type_=JSONB))


def _insert_source_publication(
    conn, publication_id, source="hal", source_id="h-1", title="Test", external_ids=None
):
    return conn.execute(
        _INSERT_SOURCE_PUB_SQL,
        {
            "source": source,
            "source_id": source_id,
            "title": title,
            "publication_id": publication_id,
            "external_ids": external_ids or {},
        },
    ).scalar_one()


def _insert_person(conn, last="Dupont", first="Jean"):
    return conn.execute(
        text(
            """
            INSERT INTO persons (last_name, first_name,
                                 last_name_normalized, first_name_normalized)
            VALUES (:last, :first, lower(:last), lower(:first)) RETURNING id
            """
        ),
        {"last": last, "first": first},
    ).scalar_one()


def _insert_authorship(conn, publication_id, person_id=None):
    return conn.execute(
        text(
            "INSERT INTO authorships (publication_id, person_id) "
            "VALUES (:pid, :person_id) RETURNING id"
        ),
        {"pid": publication_id, "person_id": person_id},
    ).scalar_one()


def _select_one(conn, sql, **binds):
    return conn.execute(text(sql), binds).one_or_none()


# ── find_by_* ──────────────────────────────────────────────────────


class TestFindByDoi:
    def test_returns_none_on_empty(self, sa_sync_conn, repo):
        assert find_by_doi(None, repo=repo) is None
        assert find_by_doi("", repo=repo) is None

    def test_finds_by_doi_case_insensitive(self, sa_sync_conn, repo):
        pub_id = _insert_publication(sa_sync_conn, doi="10.1234/ABC")
        result = find_by_doi("10.1234/abc", repo=repo)
        assert result is not None
        assert result.id == pub_id

    def test_returns_none_if_not_found(self, sa_sync_conn, repo):
        assert find_by_doi("10.1234/unknown", repo=repo) is None


class TestFindByNnt:
    def test_returns_none_on_empty(self, sa_sync_conn, repo):
        assert find_by_nnt(None, repo=repo) is None
        assert find_by_nnt("", repo=repo) is None

    def test_finds_by_nnt_in_external_ids(self, sa_sync_conn, repo):
        pub_id = _insert_publication(sa_sync_conn, doc_type="thesis")
        _insert_source_publication(
            sa_sync_conn,
            pub_id,
            source="theses",
            source_id="t-1",
            external_ids={"nnt": "2024UCAC0001"},
        )
        assert find_by_nnt("2024UCAC0001", repo=repo) == pub_id

    def test_nnt_uppercased_for_lookup(self, sa_sync_conn, repo):
        pub_id = _insert_publication(sa_sync_conn, doc_type="thesis")
        _insert_source_publication(
            sa_sync_conn,
            pub_id,
            source="theses",
            source_id="t-1",
            external_ids={"nnt": "2024UCAC0001"},
        )
        # Même en minuscules en entrée, trouve
        assert find_by_nnt("2024ucac0001", repo=repo) == pub_id


class TestFindByHalId:
    def test_returns_none_on_empty(self, sa_sync_conn, repo):
        assert repo.find_by_hal_id("") is None
        assert repo.find_by_hal_id(None) is None  # type: ignore[arg-type]

    def test_finds_via_hal_native_source(self, sa_sync_conn, repo):
        """SP HAL native : `external_ids.hal_id` est posé par le normalizer au même titre que `source_id` (convention symétrique avec NNT côté theses)."""
        pub_id = _insert_publication(sa_sync_conn)
        _insert_source_publication(
            sa_sync_conn,
            pub_id,
            source="hal",
            source_id="hal-12345",
            external_ids={"hal_id": ["hal-12345"]},
        )
        assert repo.find_by_hal_id("hal-12345") == pub_id

    def test_finds_via_external_ids_cross_source(self, sa_sync_conn, repo):
        """SP cross-source : `external_ids->>'hal_id'=hal_id` (OpenAlex/ScanR)."""
        pub_id = _insert_publication(sa_sync_conn)
        _insert_source_publication(
            sa_sync_conn,
            pub_id,
            source="openalex",
            source_id="W123",
            external_ids={"hal_id": ["hal-67890"]},
        )
        assert repo.find_by_hal_id("hal-67890") == pub_id

    def test_returns_none_if_not_found(self, sa_sync_conn, repo):
        assert repo.find_by_hal_id("hal-unknown") is None

    def test_ignores_orphan_source_publications(self, sa_sync_conn, repo):
        """Un `source_publication` HAL sans `publication_id` ne doit pas être retourné."""
        _insert_source_publication(
            sa_sync_conn,
            None,
            source="hal",
            source_id="hal-orphan",
            external_ids={"hal_id": ["hal-orphan"]},
        )
        assert repo.find_by_hal_id("hal-orphan") is None


class TestFindThesisByTitle:
    def test_returns_empty_on_missing_input(self, sa_sync_conn, repo):
        assert find_thesis_by_title("", 2024, repo=repo) == []
        assert find_thesis_by_title("t", None, repo=repo) == []

    def test_finds_only_theses(self, sa_sync_conn, repo):
        """Ne retourne que les thèses."""
        _insert_publication(sa_sync_conn, title="A", pub_year=2024, doc_type="article")
        t_id = _insert_publication(sa_sync_conn, title="A", pub_year=2024, doc_type="thesis")
        assert find_thesis_by_title("a", 2024, repo=repo) == [t_id]

    def test_returns_multiple_candidates(self, sa_sync_conn, repo):
        t1 = _insert_publication(sa_sync_conn, title="Dup", pub_year=2024, doc_type="thesis")
        t2 = _insert_publication(sa_sync_conn, title="Dup", pub_year=2024, doc_type="thesis")
        assert set(find_thesis_by_title("dup", 2024, repo=repo)) == {t1, t2}


# ── resolve_doi_conflict ───────────────────────────────────────────


class TestResolveDoiConflict:
    def test_chapter_vs_existing_book_drops_doi(self, sa_sync_conn, repo):
        """Chapitre avec DOI qui pointe vers livre : DOI retiré du chapitre."""
        existing = PubByDoi(id=1, doc_type="book", title_normalized="livre")

        doi, merge_id = resolve_doi_conflict(
            "10.x/book", "book_chapter", "chapitre", existing, repo=repo
        )
        assert doi is None
        assert merge_id is None

    def test_book_vs_existing_chapter_strips_doi_from_chapter(self, sa_sync_conn, repo):
        """Livre avec DOI existant sur un chapitre : DOI retiré du chapitre, livre garde."""
        existing_id = _insert_publication(
            sa_sync_conn, title="Chapitre", doc_type="book_chapter", doi="10.x/book"
        )
        existing = PubByDoi(id=existing_id, doc_type="book_chapter", title_normalized="chapitre")

        doi, merge_id = resolve_doi_conflict("10.x/book", "book", "livre", existing, repo=repo)
        assert doi == "10.x/book"
        assert merge_id is None
        result_doi = sa_sync_conn.execute(
            text("SELECT doi FROM publications WHERE id = :id"), {"id": existing_id}
        ).scalar_one()
        assert result_doi is None

    def test_two_chapters_different_titles_strip_both(self, sa_sync_conn, repo):
        """2 chapitres avec titres différents partageant un DOI : les 2 perdent le DOI."""
        existing_id = _insert_publication(
            sa_sync_conn, title="C1", doc_type="book_chapter", doi="10.x/shared"
        )
        existing = PubByDoi(id=existing_id, doc_type="book_chapter", title_normalized="c1")

        doi, merge_id = resolve_doi_conflict(
            "10.x/shared", "book_chapter", "c2_different", existing, repo=repo
        )
        assert doi is None
        assert merge_id is None
        result_doi = sa_sync_conn.execute(
            text("SELECT doi FROM publications WHERE id = :id"), {"id": existing_id}
        ).scalar_one()
        assert result_doi is None

    def test_two_chapters_same_title_merges(self, sa_sync_conn, repo):
        """2 chapitres avec même titre + DOI → fusion."""
        existing = PubByDoi(id=42, doc_type="book_chapter", title_normalized="same")

        doi, merge_id = resolve_doi_conflict(
            "10.x/shared", "book_chapter", "same", existing, repo=repo
        )
        assert doi == "10.x/shared"
        assert merge_id == 42

    def test_compatible_types_merge(self, sa_sync_conn, repo):
        """Types compatibles (ex: 2 articles) → fusion normale."""
        existing = PubByDoi(id=42, doc_type="article", title_normalized="a")
        doi, merge_id = resolve_doi_conflict("10.x/a", "article", "a", existing, repo=repo)
        assert doi == "10.x/a"
        assert merge_id == 42


# ── merge_publications ────────────────────────────────────────────


class TestMergePublications:
    def test_transfers_source_publications_and_authorships(self, sa_sync_conn, repo):
        target = _insert_publication(sa_sync_conn, title="Target")
        source = _insert_publication(sa_sync_conn, title="Source")
        sp_id = _insert_source_publication(sa_sync_conn, source, source="hal", source_id="h-src")

        person_id = _insert_person(sa_sync_conn)
        auth_id = _insert_authorship(sa_sync_conn, source, person_id=person_id)

        merge_publications(target, source, repo=repo)

        # source_publication repointée
        sp_pub = sa_sync_conn.execute(
            text("SELECT publication_id FROM source_publications WHERE id = :id"), {"id": sp_id}
        ).scalar_one()
        assert sp_pub == target
        # authorship repointée
        auth_pub = sa_sync_conn.execute(
            text("SELECT publication_id FROM authorships WHERE id = :id"), {"id": auth_id}
        ).scalar_one()
        assert auth_pub == target
        # source supprimée
        assert (
            _select_one(sa_sync_conn, "SELECT id FROM publications WHERE id = :id", id=source)
            is None
        )

    def test_refuses_distinct_dois(self, sa_sync_conn, repo):
        """Garde « 1 DOI = 1 publication » : deux DOI non-nuls différents → refus,
        aucune des deux n'est touchée."""
        target = _insert_publication(sa_sync_conn, doi="10.1/a")
        source = _insert_publication(sa_sync_conn, doi="10.2/b")
        with pytest.raises(DistinctDoiError):
            merge_publications(target, source, repo=repo)
        for pid in (target, source):
            assert (
                _select_one(sa_sync_conn, "SELECT id FROM publications WHERE id = :id", id=pid)
                is not None
            )

    def test_merges_when_one_doi_null(self, sa_sync_conn, repo):
        """Un seul DOI non-null : pas de conflit, fusion appliquée."""
        target = _insert_publication(sa_sync_conn, doi="10.1/a")
        source = _insert_publication(sa_sync_conn, doi=None)
        merge_publications(target, source, repo=repo)
        assert (
            _select_one(sa_sync_conn, "SELECT id FROM publications WHERE id = :id", id=source)
            is None
        )

    def test_merges_when_same_doi(self, sa_sync_conn, repo):
        """Même DOI des deux côtés : fusion (la contrainte unique ayant été retirée)."""
        target = _insert_publication(sa_sync_conn, doi="10.1/a")
        source = _insert_publication(sa_sync_conn, doi="10.1/a")
        merge_publications(target, source, repo=repo)
        assert (
            _select_one(sa_sync_conn, "SELECT id FROM publications WHERE id = :id", id=source)
            is None
        )

    def test_dedup_authorships_by_person(self, sa_sync_conn, repo):
        """Si target et source ont une authorship pour la même person, la source est jetée."""
        target = _insert_publication(sa_sync_conn, title="Target")
        source = _insert_publication(sa_sync_conn, title="Source")
        person_id = _insert_person(sa_sync_conn)
        keep_auth = _insert_authorship(sa_sync_conn, target, person_id=person_id)
        drop_auth = _insert_authorship(sa_sync_conn, source, person_id=person_id)

        merge_publications(target, source, repo=repo)

        assert (
            _select_one(sa_sync_conn, "SELECT id FROM authorships WHERE id = :id", id=keep_auth)
            is not None
        )
        assert (
            _select_one(sa_sync_conn, "SELECT id FROM authorships WHERE id = :id", id=drop_auth)
            is None
        )

    def test_enriches_journal_id(self, sa_sync_conn, repo):
        """Target sans journal_id → reçoit celui de la source (COALESCE)."""
        j_id = _insert_journal(sa_sync_conn)
        target = _insert_publication(sa_sync_conn, title="Target", doi=None, journal_id=None)
        source = _insert_publication(sa_sync_conn, title="Source", doi=None, journal_id=j_id)

        merge_publications(target, source, repo=repo)

        result = sa_sync_conn.execute(
            text("SELECT journal_id FROM publications WHERE id = :id"), {"id": target}
        ).scalar_one()
        assert result == j_id

    def test_doi_transferred_when_target_has_none(self, sa_sync_conn, repo):
        """Target sans DOI, source avec : la cible reçoit le DOI de la source."""
        target = _insert_publication(sa_sync_conn, title="Target", doi=None)
        source = _insert_publication(sa_sync_conn, title="Source", doi="10.1234/src")

        merge_publications(target, source, repo=repo)

        doi = sa_sync_conn.execute(
            text("SELECT doi FROM publications WHERE id = :id"), {"id": target}
        ).scalar_one()
        assert doi == "10.1234/src"

    def test_oa_status_upgrade_diamond_wins(self, sa_sync_conn, repo):
        """Si source est diamond, la cible devient diamond même si elle avait gold."""
        target = _insert_publication(sa_sync_conn, title="Target", oa_status="gold")
        source = _insert_publication(sa_sync_conn, title="Source", oa_status="diamond")
        merge_publications(target, source, repo=repo)
        oa_status = sa_sync_conn.execute(
            text("SELECT oa_status FROM publications WHERE id = :id"), {"id": target}
        ).scalar_one()
        assert oa_status == "diamond"

    def test_oa_status_upgrade_from_closed_to_gold(self, sa_sync_conn, repo):
        target = _insert_publication(sa_sync_conn, title="Target", oa_status="closed")
        source = _insert_publication(sa_sync_conn, title="Source", oa_status="gold")
        merge_publications(target, source, repo=repo)
        oa_status = sa_sync_conn.execute(
            text("SELECT oa_status FROM publications WHERE id = :id"), {"id": target}
        ).scalar_one()
        assert oa_status == "gold"


class TestMarkDistinct:
    def test_inserts_ordered_pair(self, sa_sync_conn):
        repo = publication_repository(sa_sync_conn)
        p1 = _insert_publication(sa_sync_conn, title="A")
        p2 = _insert_publication(sa_sync_conn, title="B")
        mark_distinct(p2, p1, repo=repo)  # ordre inverse exprès
        assert (
            _select_one(
                sa_sync_conn,
                "SELECT pub_id_a, pub_id_b FROM distinct_publications "
                "WHERE pub_id_a = :a AND pub_id_b = :b",
                a=min(p1, p2),
                b=max(p1, p2),
            )
            is not None
        )

    def test_idempotent(self, sa_sync_conn):
        repo = publication_repository(sa_sync_conn)
        p1 = _insert_publication(sa_sync_conn, title="A")
        p2 = _insert_publication(sa_sync_conn, title="B")
        mark_distinct(p1, p2, repo=repo)
        mark_distinct(p1, p2, repo=repo)  # ON CONFLICT DO NOTHING
        n = sa_sync_conn.execute(
            text(
                "SELECT COUNT(*) AS n FROM distinct_publications "
                "WHERE pub_id_a = :a AND pub_id_b = :b"
            ),
            {"a": min(p1, p2), "b": max(p1, p2)},
        ).scalar_one()
        assert n == 1
