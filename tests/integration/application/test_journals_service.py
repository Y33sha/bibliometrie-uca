"""Tests de caractérisation pour application/journals.py et
application/publishers.py.

Couvre les fonctions sync (find_or_create_*, update_journal_apc,
reset_journal_apc — utilisées par le pipeline) et les fonctions async
(update_journal, update_publisher, merge_*).
"""

import pytest
from sqlalchemy import text

from application.journals import (
    find_or_create_journal,
    merge_journals,
    reset_journal_apc,
    update_journal,
    update_journal_apc,
)
from application.publishers import (
    find_or_create_publisher,
    merge_publishers,
    update_publisher,
)
from domain.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.repositories import (
    journal_repository,
    publisher_repository,
)


@pytest.fixture
def repo(db):
    return journal_repository(db)


@pytest.fixture
def pub_repo(db):
    return publisher_repository(db)


@pytest.fixture
def sa_repo(sa_sync_conn):
    return journal_repository(sa_sync_conn)


@pytest.fixture
def sa_pub_repo(sa_sync_conn):
    return publisher_repository(sa_sync_conn)


def _fetch_one(conn, sql_text: str, **params):
    """Exécute un text() SELECT sync et retourne result.first() (Row ou None)."""
    return conn.execute(text(sql_text), params).first()


# ── Helpers sync (pipeline tests) ──────────────────────────────────


def _insert_publisher(db, name="Elsevier", openalex_id=None):
    db.execute(
        """
        INSERT INTO publishers (name, name_normalized, openalex_id)
        VALUES (%s, lower(%s), %s)
        RETURNING id
        """,
        (name, name, openalex_id),
    )
    return db.fetchone()["id"]


def _insert_journal(db, title="Nature", publisher_id=None, **kwargs):
    db.execute(
        """
        INSERT INTO journals (title, title_normalized, issn, eissn, issnl,
                              publisher_id, openalex_id, apc_amount, apc_currency,
                              is_in_doaj, oa_model)
        VALUES (%s, lower(%s), %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            title,
            title,
            kwargs.get("issn"),
            kwargs.get("eissn"),
            kwargs.get("issnl"),
            publisher_id,
            kwargs.get("openalex_id"),
            kwargs.get("apc_amount"),
            kwargs.get("apc_currency"),
            kwargs.get("is_in_doaj", False),
            kwargs.get("oa_model"),
        ),
    )
    return db.fetchone()["id"]


def _insert_publication(db, title="Pub", pub_year=2024, journal_id=None):
    db.execute(
        "INSERT INTO publications (title, pub_year, journal_id) VALUES (%s, %s, %s) RETURNING id",
        (title, pub_year, journal_id),
    )
    return db.fetchone()["id"]


# ── Helpers SA sync (API tests post-migration sync-async-deduplication) ─


def _sainsert_publisher(conn, name="Elsevier", openalex_id=None):
    result = conn.execute(
        text(
            "INSERT INTO publishers (name, name_normalized, openalex_id) "
            "VALUES (:name, lower(:name), :oa_id) RETURNING id"
        ),
        {"name": name, "oa_id": openalex_id},
    )
    return result.scalar_one()


def _sainsert_journal(conn, title="Nature", publisher_id=None, **kwargs):
    result = conn.execute(
        text(
            "INSERT INTO journals (title, title_normalized, issn, eissn, issnl, "
            "                      publisher_id, openalex_id, apc_amount, apc_currency, "
            "                      is_in_doaj, oa_model) "
            "VALUES (:title, lower(:title), :issn, :eissn, :issnl, "
            "        :pub_id, :oa_id, :apc_amount, :apc_currency, "
            "        :is_in_doaj, :oa_model) RETURNING id"
        ),
        {
            "title": title,
            "issn": kwargs.get("issn"),
            "eissn": kwargs.get("eissn"),
            "issnl": kwargs.get("issnl"),
            "pub_id": publisher_id,
            "oa_id": kwargs.get("openalex_id"),
            "apc_amount": kwargs.get("apc_amount"),
            "apc_currency": kwargs.get("apc_currency"),
            "is_in_doaj": kwargs.get("is_in_doaj", False),
            "oa_model": kwargs.get("oa_model"),
        },
    )
    return result.scalar_one()


def _sainsert_publication(conn, title="Pub", pub_year=2024, journal_id=None):
    result = conn.execute(
        text(
            "INSERT INTO publications (title, pub_year, journal_id) "
            "VALUES (:title, :year, :j_id) RETURNING id"
        ),
        {"title": title, "year": pub_year, "j_id": journal_id},
    )
    return result.scalar_one()


# ── find_or_create_publisher ───────────────────────────────────────


class TestFindOrCreatePublisher:
    def test_returns_none_on_empty_name(self, db, pub_repo):
        assert find_or_create_publisher(db, None, repo=pub_repo) is None
        assert find_or_create_publisher(db, "", repo=pub_repo) is None

    def test_creates_new_publisher(self, db, pub_repo):
        pub_id = find_or_create_publisher(db, "Elsevier", repo=pub_repo)
        assert pub_id is not None
        db.execute("SELECT name FROM publishers WHERE id = %s", (pub_id,))
        assert db.fetchone()["name"] == "Elsevier"

    def test_finds_existing_by_openalex_id(self, db, pub_repo):
        existing = _insert_publisher(db, "Elsevier", openalex_id="P4310310871")
        found = find_or_create_publisher(
            db, "Elsevier BV", openalex_id="P4310310871", repo=pub_repo
        )
        assert found == existing

    def test_finds_existing_by_name_form(self, db, pub_repo):
        existing = find_or_create_publisher(db, "Elsevier", repo=pub_repo)
        found = find_or_create_publisher(db, "elsevier", repo=pub_repo)  # variante casse
        assert found == existing

    def test_attaches_openalex_id_if_missing(self, db, pub_repo):
        existing = find_or_create_publisher(db, "Elsevier", repo=pub_repo)
        find_or_create_publisher(db, "Elsevier", openalex_id="P123", repo=pub_repo)
        db.execute("SELECT openalex_id FROM publishers WHERE id = %s", (existing,))
        assert db.fetchone()["openalex_id"] == "P123"


# ── find_or_create_journal ─────────────────────────────────────────


class TestFindOrCreateJournal:
    def test_returns_none_on_empty_title(self, db, repo):
        assert find_or_create_journal(db, None, repo=repo) is None
        assert find_or_create_journal(db, "", repo=repo) is None

    def test_creates_new_journal(self, db, repo):
        j_id = find_or_create_journal(db, "Nature", issn="0028-0836", repo=repo)
        db.execute("SELECT title, issn FROM journals WHERE id = %s", (j_id,))
        row = db.fetchone()
        assert row["title"] == "Nature"
        assert row["issn"] == "0028-0836"

    def test_finds_by_openalex_id(self, db, repo):
        existing = _insert_journal(db, "Nature", openalex_id="S137773608")
        found = find_or_create_journal(db, "Nature Journal", openalex_id="S137773608", repo=repo)
        assert found == existing

    def test_finds_by_issn(self, db, repo):
        existing = _insert_journal(db, "Nature", issn="0028-0836")
        found = find_or_create_journal(db, "Nature Variant", issn="0028-0836", repo=repo)
        assert found == existing

    def test_finds_by_eissn(self, db, repo):
        existing = _insert_journal(db, "Nature", eissn="1476-4687")
        found = find_or_create_journal(db, "Nature", eissn="1476-4687", repo=repo)
        assert found == existing

    def test_finds_by_issnl(self, db, repo):
        existing = _insert_journal(db, "Nature", issnl="0028-0836")
        found = find_or_create_journal(db, "Other Title", issnl="0028-0836", repo=repo)
        assert found == existing

    def test_finds_by_name_form(self, db, repo):
        find_or_create_journal(db, "Nature", repo=repo)  # crée + enregistre form
        found = find_or_create_journal(db, "nature", repo=repo)  # variante casse
        db.execute("SELECT COUNT(*) AS n FROM journals WHERE title_normalized = 'nature'")
        assert db.fetchone()["n"] == 1
        assert found is not None

    def test_enriches_metadata_on_match(self, db, repo, pub_repo):
        """Si on trouve par ISSN, les champs vides (eissn, publisher_id) sont remplis."""
        existing = _insert_journal(db, "Nature", issn="0028-0836")
        pub_id = find_or_create_publisher(db, "Springer", repo=pub_repo)
        find_or_create_journal(
            db,
            "Nature",
            issn="0028-0836",
            eissn="1476-4687",
            publisher_id=pub_id,
            repo=repo,
        )
        db.execute("SELECT eissn, publisher_id FROM journals WHERE id = %s", (existing,))
        row = db.fetchone()
        assert row["eissn"] == "1476-4687"
        assert row["publisher_id"] == pub_id


# ── update_journal_apc / reset_journal_apc ─────────────────────────


class TestUpdateJournalApc:
    def test_updates_fields(self, db, repo):
        j_id = _insert_journal(db, "Nature")
        update_journal_apc(
            db, j_id, apc_amount=3000.0, apc_currency="EUR", is_in_doaj=True, repo=repo
        )
        db.execute(
            "SELECT apc_amount, apc_currency, is_in_doaj FROM journals WHERE id = %s",
            (j_id,),
        )
        row = db.fetchone()
        assert float(row["apc_amount"]) == 3000.0
        assert row["apc_currency"] == "EUR"
        assert row["is_in_doaj"] is True

    def test_coalesce_preserves_existing(self, db, repo):
        """Sans nouvelle valeur, les champs existants sont conservés."""
        j_id = _insert_journal(db, "Nature", apc_amount=2000.0, apc_currency="USD", is_in_doaj=True)
        update_journal_apc(db, j_id, apc_currency="EUR", repo=repo)  # juste la devise
        db.execute(
            "SELECT apc_amount, apc_currency, is_in_doaj FROM journals WHERE id = %s",
            (j_id,),
        )
        row = db.fetchone()
        assert float(row["apc_amount"]) == 2000.0
        assert row["apc_currency"] == "EUR"
        assert row["is_in_doaj"] is True


class TestUpdateJournal:
    def test_raises_not_found(self, sa_sync_conn, sa_repo):
        with pytest.raises(NotFoundError):
            update_journal(sa_sync_conn, 999999, fields={"title": "X"}, repo=sa_repo)

    def test_raises_on_empty_fields(self, sa_sync_conn, sa_repo):
        j = _sainsert_journal(sa_sync_conn, "Nature")
        with pytest.raises(ValidationError):
            update_journal(sa_sync_conn, j, fields={}, repo=sa_repo)

    def test_updates_title_and_normalizes(self, sa_sync_conn, sa_repo):
        j = _sainsert_journal(sa_sync_conn, "Old Title")
        update_journal(sa_sync_conn, j, fields={"title": "Nature Medicine"}, repo=sa_repo)
        row = _fetch_one(
            sa_sync_conn, "SELECT title, title_normalized FROM journals WHERE id = :id", id=j
        )
        assert row.title == "Nature Medicine"
        assert row.title_normalized == "nature medicine"

    def test_partial_update(self, sa_sync_conn, sa_repo):
        j = _sainsert_journal(sa_sync_conn, "Nature", issn="0028-0836")
        update_journal(sa_sync_conn, j, fields={"eissn": "1476-4687"}, repo=sa_repo)
        row = _fetch_one(sa_sync_conn, "SELECT issn, eissn FROM journals WHERE id = :id", id=j)
        assert row.issn == "0028-0836"  # inchangé
        assert row.eissn == "1476-4687"


class TestUpdatePublisher:
    def test_raises_not_found(self, sa_sync_conn, sa_pub_repo):
        with pytest.raises(NotFoundError):
            update_publisher(sa_sync_conn, 999999, fields={"name": "X"}, repo=sa_pub_repo)

    def test_raises_on_empty_fields(self, sa_sync_conn, sa_pub_repo):
        p = _sainsert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(ValidationError):
            update_publisher(sa_sync_conn, p, fields={}, repo=sa_pub_repo)

    def test_updates_name_and_normalizes(self, sa_sync_conn, sa_pub_repo):
        p = _sainsert_publisher(sa_sync_conn, "Old Name")
        update_publisher(sa_sync_conn, p, fields={"name": "Springer Nature"}, repo=sa_pub_repo)
        row = _fetch_one(
            sa_sync_conn, "SELECT name, name_normalized FROM publishers WHERE id = :id", id=p
        )
        assert row.name == "Springer Nature"
        assert row.name_normalized == "springer nature"


class TestResetJournalApc:
    def test_resets_only_openalex_journals(self, db, repo):
        j1 = _insert_journal(db, "Nature", openalex_id="S1", apc_amount=3000.0, is_in_doaj=True)
        j2 = _insert_journal(db, "Manual", openalex_id=None, apc_amount=500.0, is_in_doaj=True)

        n = reset_journal_apc(db, repo=repo)

        assert n == 1
        db.execute("SELECT apc_amount, is_in_doaj FROM journals WHERE id = %s", (j1,))
        row = db.fetchone()
        assert row["apc_amount"] is None
        assert row["is_in_doaj"] is False
        # j2 intact
        db.execute("SELECT apc_amount, is_in_doaj FROM journals WHERE id = %s", (j2,))
        row = db.fetchone()
        assert float(row["apc_amount"]) == 500.0
        assert row["is_in_doaj"] is True


# ── merge_publishers ───────────────────────────────────────────────


class TestMergePublishers:
    def test_raises_on_self_merge(self, sa_sync_conn, sa_repo, sa_pub_repo):
        p_id = _sainsert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(ConflictError, match="lui-même"):
            merge_publishers(
                sa_sync_conn,
                p_id,
                p_id,
                publisher_repo=sa_pub_repo,
                journal_repo=sa_repo,
            )

    def test_transfers_journals_and_deletes_source(self, sa_sync_conn, sa_repo, sa_pub_repo):
        target = _sainsert_publisher(sa_sync_conn, "Target")
        source = _sainsert_publisher(sa_sync_conn, "Source")
        j1 = _sainsert_journal(sa_sync_conn, "Journal 1", publisher_id=source)

        merge_publishers(
            sa_sync_conn, target, source, publisher_repo=sa_pub_repo, journal_repo=sa_repo
        )

        assert (
            _fetch_one(sa_sync_conn, "SELECT id FROM publishers WHERE id = :id", id=source)
        ) is None  # source supprimée
        row = _fetch_one(sa_sync_conn, "SELECT publisher_id FROM journals WHERE id = :id", id=j1)
        assert row.publisher_id == target

    def test_merges_same_title_journals(self, sa_sync_conn, sa_repo, sa_pub_repo):
        """Si cible et source ont un journal de même titre, ils sont fusionnés."""
        target = _sainsert_publisher(sa_sync_conn, "Target")
        source = _sainsert_publisher(sa_sync_conn, "Source")
        jt = _sainsert_journal(sa_sync_conn, "Nature", publisher_id=target, issn="0028-0836")
        js = _sainsert_journal(sa_sync_conn, "Nature", publisher_id=source, eissn="1476-4687")
        _sainsert_publication(sa_sync_conn, journal_id=js)

        merge_publishers(
            sa_sync_conn, target, source, publisher_repo=sa_pub_repo, journal_repo=sa_repo
        )

        # Journal source supprimé
        assert (_fetch_one(sa_sync_conn, "SELECT id FROM journals WHERE id = :id", id=js)) is None
        # Journal cible enrichi
        row = _fetch_one(sa_sync_conn, "SELECT issn, eissn FROM journals WHERE id = :id", id=jt)
        assert row.issn == "0028-0836"
        assert row.eissn == "1476-4687"

    def test_raises_on_issn_conflict(self, sa_sync_conn, sa_repo, sa_pub_repo):
        target = _sainsert_publisher(sa_sync_conn, "Target")
        source = _sainsert_publisher(sa_sync_conn, "Source")
        _sainsert_journal(sa_sync_conn, "Nature", publisher_id=target, issn="0028-0836")
        _sainsert_journal(sa_sync_conn, "Nature", publisher_id=source, issn="9999-9999")

        with pytest.raises(ConflictError, match="Conflit issn"):
            merge_publishers(
                sa_sync_conn,
                target,
                source,
                publisher_repo=sa_pub_repo,
                journal_repo=sa_repo,
            )

    def test_enriches_target_flags(self, sa_sync_conn, sa_repo, sa_pub_repo):
        """is_predatory = OR logique : vrai si l'une des sources l'était."""
        target = _sainsert_publisher(sa_sync_conn, "Target")
        source = _sainsert_publisher(sa_sync_conn, "Source")
        sa_sync_conn.execute(
            text("UPDATE publishers SET is_predatory = TRUE WHERE id = :id"), {"id": source}
        )

        merge_publishers(
            sa_sync_conn, target, source, publisher_repo=sa_pub_repo, journal_repo=sa_repo
        )

        row = _fetch_one(
            sa_sync_conn, "SELECT is_predatory FROM publishers WHERE id = :id", id=target
        )
        assert row.is_predatory is True

    def test_transfers_openalex_id_when_target_has_none(self, sa_sync_conn, sa_repo, sa_pub_repo):
        """Target sans openalex_id, source avec : la cible reçoit celui de la source."""
        target = _sainsert_publisher(sa_sync_conn, "Target", openalex_id=None)
        source = _sainsert_publisher(sa_sync_conn, "Source", openalex_id="P999")
        merge_publishers(
            sa_sync_conn, target, source, publisher_repo=sa_pub_repo, journal_repo=sa_repo
        )
        row = _fetch_one(
            sa_sync_conn, "SELECT openalex_id FROM publishers WHERE id = :id", id=target
        )
        assert row.openalex_id == "P999"

    def test_keeps_target_openalex_id_when_both_set(self, sa_sync_conn, sa_repo, sa_pub_repo):
        """Si les deux ont un openalex_id, celui de la cible est conservé."""
        target = _sainsert_publisher(sa_sync_conn, "Target", openalex_id="P_TARGET")
        source = _sainsert_publisher(sa_sync_conn, "Source", openalex_id="P_SOURCE")
        merge_publishers(
            sa_sync_conn, target, source, publisher_repo=sa_pub_repo, journal_repo=sa_repo
        )
        row = _fetch_one(
            sa_sync_conn, "SELECT openalex_id FROM publishers WHERE id = :id", id=target
        )
        assert row.openalex_id == "P_TARGET"


# ── merge_journals ─────────────────────────────────────────────────


class TestMergeJournals:
    def test_raises_on_self_merge(self, sa_sync_conn, sa_repo):
        j_id = _sainsert_journal(sa_sync_conn, "Nature")
        with pytest.raises(ConflictError, match="lui-même"):
            merge_journals(sa_sync_conn, j_id, j_id, repo=sa_repo)

    def test_transfers_publications(self, sa_sync_conn, sa_repo):
        target = _sainsert_journal(sa_sync_conn, "Target")
        source = _sainsert_journal(sa_sync_conn, "Source")
        pub_id = _sainsert_publication(sa_sync_conn, journal_id=source)

        merge_journals(sa_sync_conn, target, source, repo=sa_repo)

        row = _fetch_one(
            sa_sync_conn, "SELECT journal_id FROM publications WHERE id = :id", id=pub_id
        )
        assert row.journal_id == target
        assert (
            _fetch_one(sa_sync_conn, "SELECT id FROM journals WHERE id = :id", id=source)
        ) is None

    def test_enriches_target_metadata(self, sa_sync_conn, sa_repo):
        target = _sainsert_journal(sa_sync_conn, "Target")  # pas d'ISSN
        source = _sainsert_journal(
            sa_sync_conn, "Source", issn="1234-5678", eissn="9999-0000", is_in_doaj=True
        )

        merge_journals(sa_sync_conn, target, source, repo=sa_repo)

        row = _fetch_one(
            sa_sync_conn,
            "SELECT issn, eissn, is_in_doaj FROM journals WHERE id = :id",
            id=target,
        )
        assert row.issn == "1234-5678"
        assert row.eissn == "9999-0000"
        assert row.is_in_doaj is True

    def test_does_not_overwrite_existing_fields(self, sa_sync_conn, sa_repo):
        """COALESCE : les champs renseignés dans la cible sont préservés."""
        target = _sainsert_journal(sa_sync_conn, "Target", issn="0028-0836")
        source = _sainsert_journal(sa_sync_conn, "Source", issn="1234-5678")

        # ISSN cible existe déjà → COALESCE le garde
        merge_journals(sa_sync_conn, target, source, repo=sa_repo)

        row = _fetch_one(sa_sync_conn, "SELECT issn FROM journals WHERE id = :id", id=target)
        assert row.issn == "0028-0836"
