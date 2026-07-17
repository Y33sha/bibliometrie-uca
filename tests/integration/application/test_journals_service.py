"""Tests de caractérisation pour application/journals/core.py et
application/publishers/core.py.

Couvre les fonctions sync (find_or_create_*, update_journal_apc — utilisées
par le pipeline) et les fonctions async (update_journal, update_publisher,
merge_*).
"""

import pytest
from sqlalchemy import text

from application.ports.repositories.journal_repository import JournalUpdate
from application.ports.repositories.publisher_repository import PublisherUpdate
from application.services.journals.core import (
    find_or_create_journal,
    merge_journals,
    requalify_publications_for_journal,
    update_journal,
    update_journal_apc,
)
from application.services.publishers.core import (
    find_or_create_publisher,
    merge_publishers,
    update_publisher,
)
from domain.errors import (
    NotFoundError,
    PublisherMergeBlockedError,
    ValidationError,
)
from infrastructure.queries.pipeline.metadata_correction import PgMetadataCorrectionQueries
from infrastructure.repositories import (
    journal_repository,
    publication_repository,
    publisher_repository,
)

# Stateless (connexion passée aux méthodes) → une instance module suffit.
_CORRECTION_QUERIES = PgMetadataCorrectionQueries()


@pytest.fixture
def repo(sa_sync_conn):
    return journal_repository(sa_sync_conn)


@pytest.fixture
def pub_repo(sa_sync_conn):
    return publisher_repository(sa_sync_conn)


@pytest.fixture
def publication_repo(sa_sync_conn):
    return publication_repository(sa_sync_conn)


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
            oa_model="full_oa",
        )
        j = repo.find_by_id(jid)
        assert j is not None
        assert j.title == "PLOS ONE"
        assert j.publisher_id == pub_id
        assert j.issn == "1932-6203"
        assert j.eissn == "1932-6203"
        assert j.openalex_id == "S202381698"
        assert j.is_in_doaj is True
        assert j.oa_model == "full_oa"


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


# ── update_journal_apc ─────────────────────────────────────────────


class TestUpdateJournalApc:
    def test_updates_fields(self, sa_sync_conn, repo):
        j_id = _insert_journal(sa_sync_conn, "Nature")
        update_journal_apc(j_id, apc_amount=3000.0, apc_currency="EUR", repo=repo)
        row = _fetch_one(
            sa_sync_conn,
            "SELECT apc_amount, apc_currency FROM journals WHERE id = :id",
            id=j_id,
        )
        assert float(row.apc_amount) == 3000.0
        assert row.apc_currency == "EUR"

    def test_coalesce_preserves_existing_and_leaves_is_in_doaj(self, sa_sync_conn, repo):
        """Sans nouvelle valeur, l'APC existant est conservé ; `is_in_doaj` (autorité
        DOAJ) n'est jamais touché par l'enrichissement APC."""
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
            update_journal(999999, update=JournalUpdate(title="X"), repo=repo)

    def test_raises_on_empty_fields(self, sa_sync_conn, repo):
        j = _insert_journal(sa_sync_conn, "Nature")
        with pytest.raises(ValidationError):
            update_journal(j, update=JournalUpdate(), repo=repo)

    def test_updates_title_and_normalizes(self, sa_sync_conn, repo):
        j = _insert_journal(sa_sync_conn, "Old Title")
        update_journal(j, update=JournalUpdate(title="Nature Medicine"), repo=repo)
        row = _fetch_one(
            sa_sync_conn, "SELECT title, title_normalized FROM journals WHERE id = :id", id=j
        )
        assert row.title == "Nature Medicine"
        assert row.title_normalized == "nature medicine"

    def test_partial_update(self, sa_sync_conn, repo):
        j = _insert_journal(sa_sync_conn, "Nature", issn="0028-0836")
        update_journal(j, update=JournalUpdate(eissn="1476-4687"), repo=repo)
        row = _fetch_one(sa_sync_conn, "SELECT issn, eissn FROM journals WHERE id = :id", id=j)
        assert row.issn == "0028-0836"
        assert row.eissn == "1476-4687"


class TestUpdatePublisher:
    def test_raises_not_found(self, sa_sync_conn, pub_repo):
        with pytest.raises(NotFoundError):
            update_publisher(999999, update=PublisherUpdate(name="X"), repo=pub_repo)

    def test_raises_on_empty_fields(self, sa_sync_conn, pub_repo):
        p = _insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(ValidationError):
            update_publisher(p, update=PublisherUpdate(), repo=pub_repo)

    def test_updates_name_and_normalizes(self, sa_sync_conn, pub_repo):
        p = _insert_publisher(sa_sync_conn, "Old Name")
        update_publisher(p, update=PublisherUpdate(name="Springer Nature"), repo=pub_repo)
        row = _fetch_one(
            sa_sync_conn, "SELECT name, name_normalized FROM publishers WHERE id = :id", id=p
        )
        assert row.name == "Springer Nature"
        assert row.name_normalized == "springer nature"


# ── merge_publishers ───────────────────────────────────────────────


class TestMergePublishers:
    def test_raises_on_self_merge(self, sa_sync_conn, repo, pub_repo, publication_repo):
        p_id = _insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(ValidationError, match="lui-même"):
            merge_publishers(
                p_id,
                p_id,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                publisher_repo=pub_repo,
                journal_repo=repo,
                pub_repo=publication_repo,
            )

    def test_raises_on_missing_target(self, sa_sync_conn, repo, pub_repo, publication_repo):
        p_id = _insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(NotFoundError, match="cible"):
            merge_publishers(
                999999,
                p_id,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                publisher_repo=pub_repo,
                journal_repo=repo,
                pub_repo=publication_repo,
            )

    def test_raises_on_missing_source(self, sa_sync_conn, repo, pub_repo, publication_repo):
        p_id = _insert_publisher(sa_sync_conn, "Elsevier")
        with pytest.raises(NotFoundError, match="source"):
            merge_publishers(
                p_id,
                999999,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                publisher_repo=pub_repo,
                journal_repo=repo,
                pub_repo=publication_repo,
            )

    def test_transfers_journals_and_deletes_source(
        self, sa_sync_conn, repo, pub_repo, publication_repo
    ):
        target = _insert_publisher(sa_sync_conn, "Target")
        source = _insert_publisher(sa_sync_conn, "Source")
        j1 = _insert_journal(sa_sync_conn, "Journal 1", publisher_id=source)

        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            publisher_repo=pub_repo,
            journal_repo=repo,
            pub_repo=publication_repo,
        )

        assert (
            _fetch_one(sa_sync_conn, "SELECT id FROM publishers WHERE id = :id", id=source)
        ) is None
        row = _fetch_one(sa_sync_conn, "SELECT publisher_id FROM journals WHERE id = :id", id=j1)
        assert row.publisher_id == target

    def test_merges_same_title_journals(self, sa_sync_conn, repo, pub_repo, publication_repo):
        """Si cible et source ont un journal de même titre, ils sont fusionnés."""
        target = _insert_publisher(sa_sync_conn, "Target")
        source = _insert_publisher(sa_sync_conn, "Source")
        jt = _insert_journal(sa_sync_conn, "Nature", publisher_id=target, issn="0028-0836")
        js = _insert_journal(sa_sync_conn, "Nature", publisher_id=source, eissn="1476-4687")
        _insert_publication(sa_sync_conn, journal_id=js)

        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            publisher_repo=pub_repo,
            journal_repo=repo,
            pub_repo=publication_repo,
        )

        assert (_fetch_one(sa_sync_conn, "SELECT id FROM journals WHERE id = :id", id=js)) is None
        row = _fetch_one(sa_sync_conn, "SELECT issn, eissn FROM journals WHERE id = :id", id=jt)
        assert row.issn == "0028-0836"
        assert row.eissn == "1476-4687"

    def test_merges_same_title_journals_with_only_source_openalex_id(
        self, sa_sync_conn, repo, pub_repo, publication_repo
    ):
        """Cible sans openalex_id, source avec : la fusion doit déplacer
        l'openalex_id du source vers la cible sans violer UNIQUE(openalex_id)."""
        target = _insert_publisher(sa_sync_conn, "Target")
        source = _insert_publisher(sa_sync_conn, "Source")
        jt = _insert_journal(sa_sync_conn, "Nature", publisher_id=target)
        js = _insert_journal(sa_sync_conn, "Nature", publisher_id=source, openalex_id="S4210225546")

        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            publisher_repo=pub_repo,
            journal_repo=repo,
            pub_repo=publication_repo,
        )

        assert (_fetch_one(sa_sync_conn, "SELECT id FROM journals WHERE id = :id", id=js)) is None
        row = _fetch_one(sa_sync_conn, "SELECT openalex_id FROM journals WHERE id = :id", id=jt)
        assert row.openalex_id == "S4210225546"

    def test_raises_blocked_error_on_issn_conflict(
        self, sa_sync_conn, repo, pub_repo, publication_repo
    ):
        target = _insert_publisher(sa_sync_conn, "Target")
        source = _insert_publisher(sa_sync_conn, "Source")
        jt = _insert_journal(sa_sync_conn, "Nature", publisher_id=target, issn="0028-0836")
        js = _insert_journal(sa_sync_conn, "Nature", publisher_id=source, issn="9999-9999")

        with pytest.raises(PublisherMergeBlockedError) as exc_info:
            merge_publishers(
                target,
                source,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                publisher_repo=pub_repo,
                journal_repo=repo,
                pub_repo=publication_repo,
            )

        blockers = exc_info.value.blocking_journals
        assert len(blockers) == 1
        b = blockers[0]
        assert b["target_journal_id"] == jt
        assert b["source_journal_id"] == js
        assert b["target_title"] == "Nature"
        assert b["source_title"] == "Nature"
        assert "ISSN" in b["reason"]
        assert "0028-0836" in b["reason"] and "9999-9999" in b["reason"]

    def test_blocks_when_target_has_internal_duplicate_titles(
        self, sa_sync_conn, repo, pub_repo, publication_repo
    ):
        """Si la cible a 2 journaux au même titre et la source en a 1, la fusion
        N→1 casserait. On flagge ces paires comme blockers."""
        target = _insert_publisher(sa_sync_conn, "Target")
        source = _insert_publisher(sa_sync_conn, "Source")
        _insert_journal(sa_sync_conn, "Nature", publisher_id=target, issn="0028-0836")
        _insert_journal(sa_sync_conn, "Nature", publisher_id=target, eissn="1476-4687")
        _insert_journal(sa_sync_conn, "Nature", publisher_id=source)

        with pytest.raises(PublisherMergeBlockedError) as exc_info:
            merge_publishers(
                target,
                source,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                publisher_repo=pub_repo,
                journal_repo=repo,
                pub_repo=publication_repo,
            )

        blockers = exc_info.value.blocking_journals
        assert len(blockers) == 2
        for b in blockers:
            assert "doublon interne" in b["reason"]

    def test_collects_all_blockers_in_one_pass(
        self, sa_sync_conn, repo, pub_repo, publication_repo
    ):
        """Plusieurs paires de revues bloquantes → toutes remontées d'un coup."""
        target = _insert_publisher(sa_sync_conn, "Target")
        source = _insert_publisher(sa_sync_conn, "Source")
        _insert_journal(sa_sync_conn, "Rev1", publisher_id=target, issn="1111-1111")
        _insert_journal(sa_sync_conn, "Rev1", publisher_id=source, issn="2222-2222")
        _insert_journal(sa_sync_conn, "Rev2", publisher_id=target, eissn="3333-3333")
        _insert_journal(sa_sync_conn, "Rev2", publisher_id=source, eissn="4444-4444")

        with pytest.raises(PublisherMergeBlockedError) as exc_info:
            merge_publishers(
                target,
                source,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                publisher_repo=pub_repo,
                journal_repo=repo,
                pub_repo=publication_repo,
            )

        assert len(exc_info.value.blocking_journals) == 2

    def test_transfers_openalex_id_when_target_has_none(
        self, sa_sync_conn, repo, pub_repo, publication_repo
    ):
        """Target sans openalex_id, source avec : la cible reçoit celui de la source."""
        target = _insert_publisher(sa_sync_conn, "Target", openalex_id=None)
        source = _insert_publisher(sa_sync_conn, "Source", openalex_id="P999")
        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            publisher_repo=pub_repo,
            journal_repo=repo,
            pub_repo=publication_repo,
        )
        row = _fetch_one(
            sa_sync_conn, "SELECT openalex_id FROM publishers WHERE id = :id", id=target
        )
        assert row.openalex_id == "P999"

    def test_keeps_target_openalex_id_when_both_set(
        self, sa_sync_conn, repo, pub_repo, publication_repo
    ):
        """Si les deux ont un openalex_id, celui de la cible est conservé."""
        target = _insert_publisher(sa_sync_conn, "Target", openalex_id="P_TARGET")
        source = _insert_publisher(sa_sync_conn, "Source", openalex_id="P_SOURCE")
        merge_publishers(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            publisher_repo=pub_repo,
            journal_repo=repo,
            pub_repo=publication_repo,
        )
        row = _fetch_one(
            sa_sync_conn, "SELECT openalex_id FROM publishers WHERE id = :id", id=target
        )
        assert row.openalex_id == "P_TARGET"


# ── merge_journals ─────────────────────────────────────────────────


class TestMergeJournals:
    def test_raises_on_self_merge(self, sa_sync_conn, repo, publication_repo):
        j_id = _insert_journal(sa_sync_conn, "Nature")
        with pytest.raises(ValidationError, match="lui-même"):
            merge_journals(
                j_id,
                j_id,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                repo=repo,
                pub_repo=publication_repo,
            )

    def test_raises_on_missing_target(self, sa_sync_conn, repo, publication_repo):
        j_id = _insert_journal(sa_sync_conn, "Nature")
        with pytest.raises(NotFoundError, match="cible"):
            merge_journals(
                999999,
                j_id,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                repo=repo,
                pub_repo=publication_repo,
            )

    def test_raises_on_missing_source(self, sa_sync_conn, repo, publication_repo):
        j_id = _insert_journal(sa_sync_conn, "Nature")
        with pytest.raises(NotFoundError, match="source"):
            merge_journals(
                j_id,
                999999,
                conn=sa_sync_conn,
                correction_queries=_CORRECTION_QUERIES,
                repo=repo,
                pub_repo=publication_repo,
            )

    def test_transfers_publications(self, sa_sync_conn, repo, publication_repo):
        target = _insert_journal(sa_sync_conn, "Target")
        source = _insert_journal(sa_sync_conn, "Source")
        pub_id = _insert_publication(sa_sync_conn, journal_id=source)
        # ≥1 source_publication : sinon `refresh_from_sources` (déclenché par la
        # requalification post-merge) supprimerait la publication comme orpheline.
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_publications "
                "(source, source_id, title, pub_year, journal_id, publication_id) "
                "VALUES ('openalex', 'W-transfer', 'T', 2024, :jid, :pid)"
            ),
            {"jid": source, "pid": pub_id},
        )

        merge_journals(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            repo=repo,
            pub_repo=publication_repo,
        )

        row = _fetch_one(
            sa_sync_conn, "SELECT journal_id FROM publications WHERE id = :id", id=pub_id
        )
        assert row.journal_id == target
        assert (
            _fetch_one(sa_sync_conn, "SELECT id FROM journals WHERE id = :id", id=source)
        ) is None

    def test_enriches_target_metadata(self, sa_sync_conn, repo, publication_repo):
        target = _insert_journal(sa_sync_conn, "Target")
        source = _insert_journal(
            sa_sync_conn, "Source", issn="1234-5678", eissn="9999-0000", is_in_doaj=True
        )

        merge_journals(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            repo=repo,
            pub_repo=publication_repo,
        )

        row = _fetch_one(
            sa_sync_conn,
            "SELECT issn, eissn, is_in_doaj FROM journals WHERE id = :id",
            id=target,
        )
        assert row.issn == "1234-5678"
        assert row.eissn == "9999-0000"
        assert row.is_in_doaj is True

    def test_does_not_overwrite_existing_fields(self, sa_sync_conn, repo, publication_repo):
        """COALESCE : les champs renseignés dans la cible sont préservés."""
        target = _insert_journal(sa_sync_conn, "Target", issn="0028-0836")
        source = _insert_journal(sa_sync_conn, "Source", issn="1234-5678")

        merge_journals(
            target,
            source,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            repo=repo,
            pub_repo=publication_repo,
        )

        row = _fetch_one(sa_sync_conn, "SELECT issn FROM journals WHERE id = :id", id=target)
        assert row.issn == "0028-0836"

    def test_requalifies_absorbed_publications_against_target_type(
        self, sa_sync_conn, repo, publication_repo
    ):
        """Fusionner une revue dans un média retype ses publications en `media`.

        Régression : avant ce hook, le merge repointait `journal_id` mais laissait
        les `doc_type` des publications absorbées inchangés.
        """
        media = _insert_journal(sa_sync_conn, "Le Monde")
        revue = _insert_journal(sa_sync_conn, "Revue X")
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'media' WHERE id = :id"), {"id": media}
        )
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'journal' WHERE id = :id"), {"id": revue}
        )
        pub = _insert_publication(sa_sync_conn, journal_id=revue)
        sa_sync_conn.execute(
            text("UPDATE publications SET doc_type = 'article' WHERE id = :id"), {"id": pub}
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_publications "
                "(source, source_id, title, pub_year, doc_type, journal_id, publication_id) "
                "VALUES ('openalex', 'W-merge-requalif', 'T', 2024, 'article', :jid, :pid)"
            ),
            {"jid": revue, "pid": pub},
        )

        merge_journals(
            media,
            revue,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            repo=repo,
            pub_repo=publication_repo,
        )

        row = _fetch_one(
            sa_sync_conn, "SELECT doc_type, journal_id FROM publications WHERE id = :id", id=pub
        )
        assert row.journal_id == media
        assert row.doc_type == "media"


# ── requalify_publications_for_journal (persistance SP + auto-cicatrisation) ──


class TestRequalifyPublicationsForJournal:
    def _seed(self, conn):
        """Journal 'journal' + une publication 'article' attestée par une SP 'article'."""
        journal = _insert_journal(conn, "Revue X")
        conn.execute(
            text("UPDATE journals SET journal_type = 'journal' WHERE id = :id"), {"id": journal}
        )
        pub = _insert_publication(conn, journal_id=journal)
        conn.execute(
            text("UPDATE publications SET doc_type = 'article' WHERE id = :id"), {"id": pub}
        )
        sp = conn.execute(
            text(
                "INSERT INTO source_publications "
                "(source, source_id, title, pub_year, doc_type, journal_id, publication_id) "
                "VALUES ('openalex', 'W-requalif', 'T', 2024, 'article', :jid, :pid) RETURNING id"
            ),
            {"jid": journal, "pid": pub},
        ).scalar_one()
        return journal, pub, sp

    def test_persists_sp_correction_and_retypes_publication(self, sa_sync_conn, publication_repo):
        journal, pub, sp = self._seed(sa_sync_conn)
        # Le caller a déjà basculé le type (comme update_journal).
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'media' WHERE id = :id"), {"id": journal}
        )

        count = requalify_publications_for_journal(
            journal,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            pub_repo=publication_repo,
        )
        assert count == 1

        sp_row = _fetch_one(
            sa_sync_conn,
            "SELECT doc_type, raw_metadata FROM source_publications WHERE id = :id",
            id=sp,
        )
        # La colonne SP est persistée (ce que lira le matcher), avec le brut réversible.
        assert sp_row.doc_type == "media"
        assert sp_row.raw_metadata == {
            "doc_type": {"raw": "article", "corrected_by": "JOURNAL_TYPE_MEDIA_TO_MEDIA"}
        }
        pub_row = _fetch_one(
            sa_sync_conn, "SELECT doc_type FROM publications WHERE id = :id", id=pub
        )
        assert pub_row.doc_type == "media"

    def test_self_heals_when_type_reverts(self, sa_sync_conn, publication_repo):
        journal, pub, sp = self._seed(sa_sync_conn)
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'media' WHERE id = :id"), {"id": journal}
        )
        requalify_publications_for_journal(
            journal,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            pub_repo=publication_repo,
        )

        # Le type revient à 'journal' : la correction doit être défaite, le brut restauré.
        sa_sync_conn.execute(
            text("UPDATE journals SET journal_type = 'journal' WHERE id = :id"), {"id": journal}
        )
        count = requalify_publications_for_journal(
            journal,
            conn=sa_sync_conn,
            correction_queries=_CORRECTION_QUERIES,
            pub_repo=publication_repo,
        )
        assert count == 1

        sp_row = _fetch_one(
            sa_sync_conn,
            "SELECT doc_type, raw_metadata FROM source_publications WHERE id = :id",
            id=sp,
        )
        assert sp_row.doc_type == "article"
        assert sp_row.raw_metadata == {}
        pub_row = _fetch_one(
            sa_sync_conn, "SELECT doc_type FROM publications WHERE id = :id", id=pub
        )
        assert pub_row.doc_type == "article"
