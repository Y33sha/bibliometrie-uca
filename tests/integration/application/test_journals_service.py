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
def repo(sa_sync_conn):
    return journal_repository(sa_sync_conn)


@pytest.fixture
def pub_repo(sa_sync_conn):
    return publisher_repository(sa_sync_conn)


def _fetch_one(conn, sql_text: str, **params):
    """Exécute un text() SELECT sync et retourne result.first() (Row ou None)."""
    return conn.execute(text(sql_text), params).first()


# ── Helpers ──────────────────────────────────────────────────────


def _insert_publisher(conn, name="Elsevier", openalex_id=None):
    return conn.execute(
        text(
            "INSERT INTO publishers (name, name_normalized, openalex_id) "
            "VALUES (:name, lower(:name), :oa_id) RETURNING id"
        ),
        {"name": name, "oa_id": openalex_id},
    ).scalar_one()


def _insert_journal(conn, title="Nature", publisher_id=None, **kwargs):
    return conn.execute(
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
    ).scalar_one()


def _insert_publication(conn, title="Pub", pub_year=2024, journal_id=None):
    return conn.execute(
        text(
            "INSERT INTO publications (title, pub_year, journal_id) "
            "VALUES (:title, :year, :j_id) RETURNING id"
        ),
        {"title": title, "year": pub_year, "j_id": journal_id},
    ).scalar_one()


# ── find_by_id (hydratation aggregates) ────────────────────────────


class TestPublisherFindById:
    def test_returns_none_if_missing(self, pub_repo):
        assert pub_repo.find_by_id(999999) is None

    def test_hydrates(self, sa_sync_conn, pub_repo):
        pub_id = _insert_publisher(sa_sync_conn, "Elsevier", openalex_id="P123")
        p = pub_repo.find_by_id(pub_id)
        assert p is not None
        assert p.id == pub_id
        assert p.name == "Elsevier"
        assert p.openalex_id == "P123"
        assert p.is_predatory is False


class TestJournalFindById:
    def test_returns_none_if_missing(self, repo):
        assert repo.find_by_id(999999) is None

    def test_hydrates_minimal(self, sa_sync_conn, repo):
        jid = _insert_journal(sa_sync_conn, "Nature")
        j = repo.find_by_id(jid)
        assert j is not None
        assert j.id == jid
        assert j.title == "Nature"
        assert j.publisher_id is None
        assert j.apc_currency is None
        assert j.is_in_doaj is False
        assert j.is_predatory is False

    def test_hydrates_full(self, sa_sync_conn, repo):
        pub_id = _insert_publisher(sa_sync_conn, "PLOS")
        jid = _insert_journal(
            sa_sync_conn,
            title="PLOS ONE",
            publisher_id=pub_id,
            issn="1932-6203",
            eissn="1932-6203",
            issnl="1932-6203",
            openalex_id="S202381698",
            apc_amount=1700,
            apc_currency="USD",
            is_in_doaj=True,
            oa_model="gold",
        )
        j = repo.find_by_id(jid)
        assert j is not None
        assert j.title == "PLOS ONE"
        assert j.publisher_id == pub_id
        assert j.issn == "1932-6203"
        assert j.eissn == "1932-6203"
        assert j.openalex_id == "S202381698"
        assert j.is_in_doaj is True
        assert j.oa_model == "gold"


# ── find_or_create_publisher ───────────────────────────────────────


class TestFindOrCreatePublisher:
    def test_returns_none_on_empty_name(self, sa_sync_conn, pub_repo):
        assert find_or_create_publisher(None, repo=pub_repo) is None
        assert find_or_create_publisher("", repo=pub_repo) is None

    def test_creates_new_publisher(self, sa_sync_conn, pub_repo):
        pub_id = find_or_create_publisher("Elsevier", repo=pub_repo)
        assert pub_id is not None
        row = _fetch_one(sa_sync_conn, "SELECT name FROM publishers WHERE id = :id", id=pub_id)
        assert row.name == "Elsevier"

    def test_finds_existing_by_openalex_id(self, sa_sync_conn, pub_repo):
        existing = _insert_publisher(sa_sync_conn, "Elsevier", openalex_id="P4310310871")
        found = find_or_create_publisher("Elsevier BV", openalex_id="P4310310871", repo=pub_repo)
        assert found == existing

    def test_finds_existing_by_name_form(self, sa_sync_conn, pub_repo):
        existing = find_or_create_publisher("Elsevier", repo=pub_repo)
        found = find_or_create_publisher("elsevier", repo=pub_repo)
        assert found == existing

    def test_attaches_openalex_id_if_missing(self, sa_sync_conn, pub_repo):
        existing = find_or_create_publisher("Elsevier", repo=pub_repo)
        find_or_create_publisher("Elsevier", openalex_id="P123", repo=pub_repo)
        row = _fetch_one(
            sa_sync_conn, "SELECT openalex_id FROM publishers WHERE id = :id", id=existing
        )
        assert row.openalex_id == "P123"


# ── find_or_create_journal ─────────────────────────────────────────


class TestFindOrCreateJournal:
    def test_returns_none_on_empty_title(self, sa_sync_conn, repo):
        assert find_or_create_journal(None, repo=repo) is None
        assert find_or_create_journal("", repo=repo) is None

    def test_creates_new_journal(self, sa_sync_conn, repo):
        j_id = find_or_create_journal("Nature", issn="0028-0836", repo=repo)
        row = _fetch_one(sa_sync_conn, "SELECT title, issn FROM journals WHERE id = :id", id=j_id)
        assert row.title == "Nature"
        assert row.issn == "0028-0836"

    def test_finds_by_openalex_id(self, sa_sync_conn, repo):
        existing = _insert_journal(sa_sync_conn, "Nature", openalex_id="S137773608")
        found = find_or_create_journal("Nature Journal", openalex_id="S137773608", repo=repo)
        assert found == existing

    def test_finds_by_issn(self, sa_sync_conn, repo):
        existing = _insert_journal(sa_sync_conn, "Nature", issn="0028-0836")
        found = find_or_create_journal("Nature Variant", issn="0028-0836", repo=repo)
        assert found == existing

    def test_finds_by_eissn(self, sa_sync_conn, repo):
        existing = _insert_journal(sa_sync_conn, "Nature", eissn="1476-4687")
        found = find_or_create_journal("Nature", eissn="1476-4687", repo=repo)
        assert found == existing

    def test_finds_by_issnl(self, sa_sync_conn, repo):
        existing = _insert_journal(sa_sync_conn, "Nature", issnl="0028-0836")
        found = find_or_create_journal("Other Title", issnl="0028-0836", repo=repo)
        assert found == existing

    def test_finds_by_name_form(self, sa_sync_conn, repo):
        find_or_create_journal("Nature", repo=repo)
        found = find_or_create_journal("nature", repo=repo)
        n = sa_sync_conn.execute(
            text("SELECT COUNT(*) AS n FROM journals WHERE title_normalized = 'nature'")
        ).scalar_one()
        assert n == 1
        assert found is not None

    def test_enriches_metadata_on_match(self, sa_sync_conn, repo, pub_repo):
        """Si on trouve par ISSN, les champs vides (eissn, publisher_id) sont remplis."""
        existing = _insert_journal(sa_sync_conn, "Nature", issn="0028-0836")
        pub_id = find_or_create_publisher("Springer", repo=pub_repo)
        find_or_create_journal(
            "Nature",
            issn="0028-0836",
            eissn="1476-4687",
            publisher_id=pub_id,
            repo=repo,
        )
        row = _fetch_one(
            sa_sync_conn, "SELECT eissn, publisher_id FROM journals WHERE id = :id", id=existing
        )
        assert row.eissn == "1476-4687"
        assert row.publisher_id == pub_id


# ── update_journal_apc / reset_journal_apc ─────────────────────────


class TestUpdateJournalApc:
    def test_updates_fields(self, sa_sync_conn, repo):
        j_id = _insert_journal(sa_sync_conn, "Nature")
        update_journal_apc(
            j_id,
            apc_amount=3000.0,
            apc_currency="EUR",
            is_in_doaj=True,
            repo=repo,
        )
        row = _fetch_one(
            sa_sync_conn,
            "SELECT apc_amount, apc_currency, is_in_doaj FROM journals WHERE id = :id",
            id=j_id,
        )
        assert float(row.apc_amount) == 3000.0
        assert row.apc_currency == "EUR"
        assert row.is_in_doaj is True

    def test_coalesce_preserves_existing(self, sa_sync_conn, repo):
        """Sans nouvelle valeur, les champs existants sont conservés."""
        j_id = _insert_journal(
            sa_sync_conn, "Nature", apc_amount=2000.0, apc_currency="USD", is_in_doaj=True
        )
        update_journal_apc(j_id, apc_currency="EUR", repo=repo)
        row = _fetch_one(
            sa_sync_conn,
            "SELECT apc_amount, apc_currency, is_in_doaj FROM journals WHERE id = :id",
            id=j_id,
        )
        assert float(row.apc_amount) == 2000.0
        assert row.apc_currency == "EUR"
        assert row.is_in_doaj is True


class TestUpdateJournal:
    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            update_journal(999999, fields={"title": "X"}, repo=repo)

    def test_raises_on_empty_fields(self, sa_sync_conn, repo):
        j = _insert_journal(sa_sync_conn, "Nature")
        with pytest.raises(ValidationError):
            update_journal(j, fields={}, repo=repo)

    def test_updates_title_and_normalizes(self, sa_sync_conn, repo):
        j = _insert_journal(sa_sync_conn, "Old Title")
        update_journal(j, fields={"title": "Nature Medicine"}, repo=repo)
        row = _fetch_one(
            sa_sync_conn, "SELECT title, title_normalized FROM journals WHERE id = :id", id=j
        )
        assert row.title == "Nature Medicine"
        assert row.title_normalized == "nature medicine"

    def test_partial_update(self, sa_sync_conn, repo):
        j = _insert_journal(sa_sync_conn, "Nature", issn="0028-0836")
        update_journal(j, fields={"eissn": "1476-4687"}, repo=repo)
        row = _fetch_one(sa_sync_conn, "SELECT issn, eissn FROM journals WHERE id = :id", id=j)
        assert row.issn == "0028-0836"
        assert row.eissn == "1476-4687"


class TestUpdatePublisher:
    def test_raises_not_found(self, sa_sync_conn, pub_repo):
        with pytest.raises(NotFoundError):
            update_publisher(999999, fields={"name": "X"}, repo=pub_repo)

    def test_raises_on_empty_fields(self, sa_sync_conn, pub_repo):
        p = _insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(ValidationError):
            update_publisher(p, fields={}, repo=pub_repo)

    def test_updates_name_and_normalizes(self, sa_sync_conn, pub_repo):
        p = _insert_publisher(sa_sync_conn, "Old Name")
        update_publisher(p, fields={"name": "Springer Nature"}, repo=pub_repo)
        row = _fetch_one(
            sa_sync_conn, "SELECT name, name_normalized FROM publishers WHERE id = :id", id=p
        )
        assert row.name == "Springer Nature"
        assert row.name_normalized == "springer nature"


class TestResetJournalApc:
    def test_resets_only_openalex_journals(self, sa_sync_conn, repo):
        j1 = _insert_journal(
            sa_sync_conn, "Nature", openalex_id="S1", apc_amount=3000.0, is_in_doaj=True
        )
        j2 = _insert_journal(
            sa_sync_conn, "Manual", openalex_id=None, apc_amount=500.0, is_in_doaj=True
        )

        n = reset_journal_apc(repo=repo)

        assert n == 1
        row = _fetch_one(
            sa_sync_conn, "SELECT apc_amount, is_in_doaj FROM journals WHERE id = :id", id=j1
        )
        assert row.apc_amount is None
        assert row.is_in_doaj is False
        # j2 intact
        row = _fetch_one(
            sa_sync_conn, "SELECT apc_amount, is_in_doaj FROM journals WHERE id = :id", id=j2
        )
        assert float(row.apc_amount) == 500.0
        assert row.is_in_doaj is True


# ── merge_publishers ───────────────────────────────────────────────


class TestMergePublishers:
    def test_raises_on_self_merge(self, sa_sync_conn, repo, pub_repo):
        p_id = _insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(ConflictError, match="lui-même"):
            merge_publishers(p_id, p_id, publisher_repo=pub_repo, journal_repo=repo)

    def test_transfers_journals_and_deletes_source(self, sa_sync_conn, repo, pub_repo):
        target = _insert_publisher(sa_sync_conn, "Target")
        source = _insert_publisher(sa_sync_conn, "Source")
        j1 = _insert_journal(sa_sync_conn, "Journal 1", publisher_id=source)

        merge_publishers(target, source, publisher_repo=pub_repo, journal_repo=repo)

        assert (
            _fetch_one(sa_sync_conn, "SELECT id FROM publishers WHERE id = :id", id=source)
        ) is None
        row = _fetch_one(sa_sync_conn, "SELECT publisher_id FROM journals WHERE id = :id", id=j1)
        assert row.publisher_id == target

    def test_merges_same_title_journals(self, sa_sync_conn, repo, pub_repo):
        """Si cible et source ont un journal de même titre, ils sont fusionnés."""
        target = _insert_publisher(sa_sync_conn, "Target")
        source = _insert_publisher(sa_sync_conn, "Source")
        jt = _insert_journal(sa_sync_conn, "Nature", publisher_id=target, issn="0028-0836")
        js = _insert_journal(sa_sync_conn, "Nature", publisher_id=source, eissn="1476-4687")
        _insert_publication(sa_sync_conn, journal_id=js)

        merge_publishers(target, source, publisher_repo=pub_repo, journal_repo=repo)

        assert (_fetch_one(sa_sync_conn, "SELECT id FROM journals WHERE id = :id", id=js)) is None
        row = _fetch_one(sa_sync_conn, "SELECT issn, eissn FROM journals WHERE id = :id", id=jt)
        assert row.issn == "0028-0836"
        assert row.eissn == "1476-4687"

    def test_raises_on_issn_conflict(self, sa_sync_conn, repo, pub_repo):
        target = _insert_publisher(sa_sync_conn, "Target")
        source = _insert_publisher(sa_sync_conn, "Source")
        _insert_journal(sa_sync_conn, "Nature", publisher_id=target, issn="0028-0836")
        _insert_journal(sa_sync_conn, "Nature", publisher_id=source, issn="9999-9999")

        with pytest.raises(ConflictError, match="Conflit issn"):
            merge_publishers(
                target,
                source,
                publisher_repo=pub_repo,
                journal_repo=repo,
            )

    def test_enriches_target_flags(self, sa_sync_conn, repo, pub_repo):
        """is_predatory = OR logique : vrai si l'une des sources l'était."""
        target = _insert_publisher(sa_sync_conn, "Target")
        source = _insert_publisher(sa_sync_conn, "Source")
        sa_sync_conn.execute(
            text("UPDATE publishers SET is_predatory = TRUE WHERE id = :id"), {"id": source}
        )

        merge_publishers(target, source, publisher_repo=pub_repo, journal_repo=repo)

        row = _fetch_one(
            sa_sync_conn, "SELECT is_predatory FROM publishers WHERE id = :id", id=target
        )
        assert row.is_predatory is True

    def test_transfers_openalex_id_when_target_has_none(self, sa_sync_conn, repo, pub_repo):
        """Target sans openalex_id, source avec : la cible reçoit celui de la source."""
        target = _insert_publisher(sa_sync_conn, "Target", openalex_id=None)
        source = _insert_publisher(sa_sync_conn, "Source", openalex_id="P999")
        merge_publishers(target, source, publisher_repo=pub_repo, journal_repo=repo)
        row = _fetch_one(
            sa_sync_conn, "SELECT openalex_id FROM publishers WHERE id = :id", id=target
        )
        assert row.openalex_id == "P999"

    def test_keeps_target_openalex_id_when_both_set(self, sa_sync_conn, repo, pub_repo):
        """Si les deux ont un openalex_id, celui de la cible est conservé."""
        target = _insert_publisher(sa_sync_conn, "Target", openalex_id="P_TARGET")
        source = _insert_publisher(sa_sync_conn, "Source", openalex_id="P_SOURCE")
        merge_publishers(target, source, publisher_repo=pub_repo, journal_repo=repo)
        row = _fetch_one(
            sa_sync_conn, "SELECT openalex_id FROM publishers WHERE id = :id", id=target
        )
        assert row.openalex_id == "P_TARGET"


# ── merge_journals ─────────────────────────────────────────────────


class TestMergeJournals:
    def test_raises_on_self_merge(self, sa_sync_conn, repo):
        j_id = _insert_journal(sa_sync_conn, "Nature")
        with pytest.raises(ConflictError, match="lui-même"):
            merge_journals(j_id, j_id, repo=repo)

    def test_transfers_publications(self, sa_sync_conn, repo):
        target = _insert_journal(sa_sync_conn, "Target")
        source = _insert_journal(sa_sync_conn, "Source")
        pub_id = _insert_publication(sa_sync_conn, journal_id=source)

        merge_journals(target, source, repo=repo)

        row = _fetch_one(
            sa_sync_conn, "SELECT journal_id FROM publications WHERE id = :id", id=pub_id
        )
        assert row.journal_id == target
        assert (
            _fetch_one(sa_sync_conn, "SELECT id FROM journals WHERE id = :id", id=source)
        ) is None

    def test_enriches_target_metadata(self, sa_sync_conn, repo):
        target = _insert_journal(sa_sync_conn, "Target")
        source = _insert_journal(
            sa_sync_conn, "Source", issn="1234-5678", eissn="9999-0000", is_in_doaj=True
        )

        merge_journals(target, source, repo=repo)

        row = _fetch_one(
            sa_sync_conn,
            "SELECT issn, eissn, is_in_doaj FROM journals WHERE id = :id",
            id=target,
        )
        assert row.issn == "1234-5678"
        assert row.eissn == "9999-0000"
        assert row.is_in_doaj is True

    def test_does_not_overwrite_existing_fields(self, sa_sync_conn, repo):
        """COALESCE : les champs renseignés dans la cible sont préservés."""
        target = _insert_journal(sa_sync_conn, "Target", issn="0028-0836")
        source = _insert_journal(sa_sync_conn, "Source", issn="1234-5678")

        merge_journals(target, source, repo=repo)

        row = _fetch_one(sa_sync_conn, "SELECT issn FROM journals WHERE id = :id", id=target)
        assert row.issn == "0028-0836"
