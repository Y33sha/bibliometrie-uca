"""Tests de caractérisation pour application/journals.py et
application/publishers.py (split §2.9.SRP).

Couvre les fonctions sync (find_or_create_*, update_journal_apc,
reset_journal_apc — utilisées par le pipeline) et les fonctions async
migrées §2.12 (update_journal, update_publisher, merge_*).
"""

import pytest

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
    async_journal_repository,
    async_publisher_repository,
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
def async_repo(async_db):
    return async_journal_repository(async_db)


@pytest.fixture
def async_pub_repo(async_db):
    return async_publisher_repository(async_db)


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


# ── Helpers async (API tests, §2.12) ───────────────────────────────


async def _ainsert_publisher(db, name="Elsevier", openalex_id=None):
    await db.execute(
        """
        INSERT INTO publishers (name, name_normalized, openalex_id)
        VALUES (%s, lower(%s), %s)
        RETURNING id
        """,
        (name, name, openalex_id),
    )
    row = await db.fetchone()
    return row["id"]


async def _ainsert_journal(db, title="Nature", publisher_id=None, **kwargs):
    await db.execute(
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
    row = await db.fetchone()
    return row["id"]


async def _ainsert_publication(db, title="Pub", pub_year=2024, journal_id=None):
    await db.execute(
        "INSERT INTO publications (title, pub_year, journal_id) VALUES (%s, %s, %s) RETURNING id",
        (title, pub_year, journal_id),
    )
    row = await db.fetchone()
    return row["id"]


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
    async def test_raises_not_found(self, async_db, async_repo):
        with pytest.raises(NotFoundError):
            await update_journal(async_db, 999999, fields={"title": "X"}, repo=async_repo)

    async def test_raises_on_empty_fields(self, async_db, async_repo):
        j = await _ainsert_journal(async_db, "Nature")
        with pytest.raises(ValidationError):
            await update_journal(async_db, j, fields={}, repo=async_repo)

    async def test_updates_title_and_normalizes(self, async_db, async_repo):
        j = await _ainsert_journal(async_db, "Old Title")
        await update_journal(async_db, j, fields={"title": "Nature Medicine"}, repo=async_repo)
        await async_db.execute("SELECT title, title_normalized FROM journals WHERE id = %s", (j,))
        row = await async_db.fetchone()
        assert row["title"] == "Nature Medicine"
        assert row["title_normalized"] == "nature medicine"

    async def test_partial_update(self, async_db, async_repo):
        j = await _ainsert_journal(async_db, "Nature", issn="0028-0836")
        await update_journal(async_db, j, fields={"eissn": "1476-4687"}, repo=async_repo)
        await async_db.execute("SELECT issn, eissn FROM journals WHERE id = %s", (j,))
        row = await async_db.fetchone()
        assert row["issn"] == "0028-0836"  # inchangé
        assert row["eissn"] == "1476-4687"


class TestUpdatePublisher:
    async def test_raises_not_found(self, async_db, async_pub_repo):
        with pytest.raises(NotFoundError):
            await update_publisher(async_db, 999999, fields={"name": "X"}, repo=async_pub_repo)

    async def test_raises_on_empty_fields(self, async_db, async_pub_repo):
        p = await _ainsert_publisher(async_db, "Elsevier")
        with pytest.raises(ValidationError):
            await update_publisher(async_db, p, fields={}, repo=async_pub_repo)

    async def test_updates_name_and_normalizes(self, async_db, async_pub_repo):
        p = await _ainsert_publisher(async_db, "Old Name")
        await update_publisher(async_db, p, fields={"name": "Springer Nature"}, repo=async_pub_repo)
        await async_db.execute("SELECT name, name_normalized FROM publishers WHERE id = %s", (p,))
        row = await async_db.fetchone()
        assert row["name"] == "Springer Nature"
        assert row["name_normalized"] == "springer nature"


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
    async def test_raises_on_self_merge(self, async_db, async_repo, async_pub_repo):
        p_id = await _ainsert_publisher(async_db, "Elsevier")
        with pytest.raises(ConflictError, match="lui-même"):
            await merge_publishers(
                async_db,
                p_id,
                p_id,
                publisher_repo=async_pub_repo,
                journal_repo=async_repo,
            )

    async def test_transfers_journals_and_deletes_source(
        self, async_db, async_repo, async_pub_repo
    ):
        target = await _ainsert_publisher(async_db, "Target")
        source = await _ainsert_publisher(async_db, "Source")
        j1 = await _ainsert_journal(async_db, "Journal 1", publisher_id=source)

        await merge_publishers(
            async_db, target, source, publisher_repo=async_pub_repo, journal_repo=async_repo
        )

        await async_db.execute("SELECT id FROM publishers WHERE id = %s", (source,))
        assert await async_db.fetchone() is None  # source supprimée
        await async_db.execute("SELECT publisher_id FROM journals WHERE id = %s", (j1,))
        row = await async_db.fetchone()
        assert row["publisher_id"] == target

    async def test_merges_same_title_journals(self, async_db, async_repo, async_pub_repo):
        """Si cible et source ont un journal de même titre, ils sont fusionnés."""
        target = await _ainsert_publisher(async_db, "Target")
        source = await _ainsert_publisher(async_db, "Source")
        jt = await _ainsert_journal(async_db, "Nature", publisher_id=target, issn="0028-0836")
        js = await _ainsert_journal(async_db, "Nature", publisher_id=source, eissn="1476-4687")
        await _ainsert_publication(async_db, journal_id=js)

        await merge_publishers(
            async_db, target, source, publisher_repo=async_pub_repo, journal_repo=async_repo
        )

        # Journal source supprimé
        await async_db.execute("SELECT id FROM journals WHERE id = %s", (js,))
        assert await async_db.fetchone() is None
        # Journal cible enrichi
        await async_db.execute("SELECT issn, eissn FROM journals WHERE id = %s", (jt,))
        row = await async_db.fetchone()
        assert row["issn"] == "0028-0836"
        assert row["eissn"] == "1476-4687"

    async def test_raises_on_issn_conflict(self, async_db, async_repo, async_pub_repo):
        target = await _ainsert_publisher(async_db, "Target")
        source = await _ainsert_publisher(async_db, "Source")
        await _ainsert_journal(async_db, "Nature", publisher_id=target, issn="0028-0836")
        await _ainsert_journal(async_db, "Nature", publisher_id=source, issn="9999-9999")

        with pytest.raises(ConflictError, match="Conflit issn"):
            await merge_publishers(
                async_db, target, source, publisher_repo=async_pub_repo, journal_repo=async_repo
            )

    async def test_enriches_target_flags(self, async_db, async_repo, async_pub_repo):
        """is_predatory = OR logique : vrai si l'une des sources l'était."""
        target = await _ainsert_publisher(async_db, "Target")
        source = await _ainsert_publisher(async_db, "Source")
        await async_db.execute("UPDATE publishers SET is_predatory = TRUE WHERE id = %s", (source,))

        await merge_publishers(
            async_db, target, source, publisher_repo=async_pub_repo, journal_repo=async_repo
        )

        await async_db.execute("SELECT is_predatory FROM publishers WHERE id = %s", (target,))
        row = await async_db.fetchone()
        assert row["is_predatory"] is True

    async def test_transfers_openalex_id_when_target_has_none(
        self, async_db, async_repo, async_pub_repo
    ):
        """Target sans openalex_id, source avec : la cible reçoit celui de la source."""
        target = await _ainsert_publisher(async_db, "Target", openalex_id=None)
        source = await _ainsert_publisher(async_db, "Source", openalex_id="P999")
        await merge_publishers(
            async_db, target, source, publisher_repo=async_pub_repo, journal_repo=async_repo
        )
        await async_db.execute("SELECT openalex_id FROM publishers WHERE id = %s", (target,))
        row = await async_db.fetchone()
        assert row["openalex_id"] == "P999"

    async def test_keeps_target_openalex_id_when_both_set(
        self, async_db, async_repo, async_pub_repo
    ):
        """Si les deux ont un openalex_id, celui de la cible est conservé."""
        target = await _ainsert_publisher(async_db, "Target", openalex_id="P_TARGET")
        source = await _ainsert_publisher(async_db, "Source", openalex_id="P_SOURCE")
        await merge_publishers(
            async_db, target, source, publisher_repo=async_pub_repo, journal_repo=async_repo
        )
        await async_db.execute("SELECT openalex_id FROM publishers WHERE id = %s", (target,))
        row = await async_db.fetchone()
        assert row["openalex_id"] == "P_TARGET"


# ── merge_journals ─────────────────────────────────────────────────


class TestMergeJournals:
    async def test_raises_on_self_merge(self, async_db, async_repo):
        j_id = await _ainsert_journal(async_db, "Nature")
        with pytest.raises(ConflictError, match="lui-même"):
            await merge_journals(async_db, j_id, j_id, repo=async_repo)

    async def test_transfers_publications(self, async_db, async_repo):
        target = await _ainsert_journal(async_db, "Target")
        source = await _ainsert_journal(async_db, "Source")
        pub_id = await _ainsert_publication(async_db, journal_id=source)

        await merge_journals(async_db, target, source, repo=async_repo)

        await async_db.execute("SELECT journal_id FROM publications WHERE id = %s", (pub_id,))
        row = await async_db.fetchone()
        assert row["journal_id"] == target
        await async_db.execute("SELECT id FROM journals WHERE id = %s", (source,))
        assert await async_db.fetchone() is None

    async def test_enriches_target_metadata(self, async_db, async_repo):
        target = await _ainsert_journal(async_db, "Target")  # pas d'ISSN
        source = await _ainsert_journal(
            async_db, "Source", issn="1234-5678", eissn="9999-0000", is_in_doaj=True
        )

        await merge_journals(async_db, target, source, repo=async_repo)

        await async_db.execute(
            "SELECT issn, eissn, is_in_doaj FROM journals WHERE id = %s",
            (target,),
        )
        row = await async_db.fetchone()
        assert row["issn"] == "1234-5678"
        assert row["eissn"] == "9999-0000"
        assert row["is_in_doaj"] is True

    async def test_does_not_overwrite_existing_fields(self, async_db, async_repo):
        """COALESCE : les champs renseignés dans la cible sont préservés."""
        target = await _ainsert_journal(async_db, "Target", issn="0028-0836")
        source = await _ainsert_journal(async_db, "Source", issn="1234-5678")

        # ISSN cible existe déjà → COALESCE le garde
        await merge_journals(async_db, target, source, repo=async_repo)

        await async_db.execute("SELECT issn FROM journals WHERE id = %s", (target,))
        row = await async_db.fetchone()
        assert row["issn"] == "0028-0836"
