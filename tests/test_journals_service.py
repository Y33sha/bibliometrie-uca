"""Tests de caractérisation pour services/journals.py.

Couvre find_or_create_publisher, find_or_create_journal, update_journal_apc,
reset_journal_apc, merge_publishers, merge_journals.
"""

import pytest

from services.journals import (
    find_or_create_journal,
    find_or_create_publisher,
    merge_journals,
    merge_publishers,
    reset_journal_apc,
    update_journal_apc,
)


# ── Helpers ────────────────────────────────────────────────────────

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
            title, title,
            kwargs.get("issn"), kwargs.get("eissn"), kwargs.get("issnl"),
            publisher_id, kwargs.get("openalex_id"),
            kwargs.get("apc_amount"), kwargs.get("apc_currency"),
            kwargs.get("is_in_doaj", False), kwargs.get("oa_model"),
        ),
    )
    return db.fetchone()["id"]


def _insert_publication(db, title="Pub", pub_year=2024, journal_id=None):
    db.execute(
        "INSERT INTO publications (title, pub_year, journal_id) VALUES (%s, %s, %s) RETURNING id",
        (title, pub_year, journal_id),
    )
    return db.fetchone()["id"]


# ── find_or_create_publisher ───────────────────────────────────────

class TestFindOrCreatePublisher:
    def test_returns_none_on_empty_name(self, db):
        assert find_or_create_publisher(db, None) is None
        assert find_or_create_publisher(db, "") is None

    def test_creates_new_publisher(self, db):
        pub_id = find_or_create_publisher(db, "Elsevier")
        assert pub_id is not None
        db.execute("SELECT name FROM publishers WHERE id = %s", (pub_id,))
        assert db.fetchone()["name"] == "Elsevier"

    def test_finds_existing_by_openalex_id(self, db):
        existing = _insert_publisher(db, "Elsevier", openalex_id="P4310310871")
        found = find_or_create_publisher(db, "Elsevier BV", openalex_id="P4310310871")
        assert found == existing

    def test_finds_existing_by_name_form(self, db):
        existing = find_or_create_publisher(db, "Elsevier")
        found = find_or_create_publisher(db, "elsevier")  # variante casse
        assert found == existing

    def test_attaches_openalex_id_if_missing(self, db):
        existing = find_or_create_publisher(db, "Elsevier")
        find_or_create_publisher(db, "Elsevier", openalex_id="P123")
        db.execute("SELECT openalex_id FROM publishers WHERE id = %s", (existing,))
        assert db.fetchone()["openalex_id"] == "P123"


# ── find_or_create_journal ─────────────────────────────────────────

class TestFindOrCreateJournal:
    def test_returns_none_on_empty_title(self, db):
        assert find_or_create_journal(db, None) is None
        assert find_or_create_journal(db, "") is None

    def test_creates_new_journal(self, db):
        j_id = find_or_create_journal(db, "Nature", issn="0028-0836")
        db.execute("SELECT title, issn FROM journals WHERE id = %s", (j_id,))
        row = db.fetchone()
        assert row["title"] == "Nature"
        assert row["issn"] == "0028-0836"

    def test_finds_by_openalex_id(self, db):
        existing = _insert_journal(db, "Nature", openalex_id="S137773608")
        found = find_or_create_journal(db, "Nature Journal", openalex_id="S137773608")
        assert found == existing

    def test_finds_by_issn(self, db):
        existing = _insert_journal(db, "Nature", issn="0028-0836")
        found = find_or_create_journal(db, "Nature Variant", issn="0028-0836")
        assert found == existing

    def test_finds_by_eissn(self, db):
        existing = _insert_journal(db, "Nature", eissn="1476-4687")
        found = find_or_create_journal(db, "Nature", eissn="1476-4687")
        assert found == existing

    def test_finds_by_issnl(self, db):
        existing = _insert_journal(db, "Nature", issnl="0028-0836")
        found = find_or_create_journal(db, "Other Title", issnl="0028-0836")
        assert found == existing

    def test_finds_by_name_form(self, db):
        find_or_create_journal(db, "Nature")  # crée + enregistre form
        found = find_or_create_journal(db, "nature")  # variante casse
        db.execute("SELECT COUNT(*) AS n FROM journals WHERE title_normalized = 'nature'")
        assert db.fetchone()["n"] == 1
        assert found is not None

    def test_enriches_metadata_on_match(self, db):
        """Si on trouve par ISSN, les champs vides (eissn, publisher_id) sont remplis."""
        existing = _insert_journal(db, "Nature", issn="0028-0836")
        pub_id = find_or_create_publisher(db, "Springer")
        find_or_create_journal(db, "Nature", issn="0028-0836",
                               eissn="1476-4687", publisher_id=pub_id)
        db.execute("SELECT eissn, publisher_id FROM journals WHERE id = %s", (existing,))
        row = db.fetchone()
        assert row["eissn"] == "1476-4687"
        assert row["publisher_id"] == pub_id


# ── update_journal_apc / reset_journal_apc ─────────────────────────

class TestUpdateJournalApc:
    def test_updates_fields(self, db):
        j_id = _insert_journal(db, "Nature")
        update_journal_apc(db, j_id, apc_amount=3000.0, apc_currency="EUR",
                           is_in_doaj=True)
        db.execute(
            "SELECT apc_amount, apc_currency, is_in_doaj FROM journals WHERE id = %s",
            (j_id,),
        )
        row = db.fetchone()
        assert float(row["apc_amount"]) == 3000.0
        assert row["apc_currency"] == "EUR"
        assert row["is_in_doaj"] is True

    def test_coalesce_preserves_existing(self, db):
        """Sans nouvelle valeur, les champs existants sont conservés."""
        j_id = _insert_journal(db, "Nature", apc_amount=2000.0,
                               apc_currency="USD", is_in_doaj=True)
        update_journal_apc(db, j_id, apc_currency="EUR")  # juste la devise
        db.execute(
            "SELECT apc_amount, apc_currency, is_in_doaj FROM journals WHERE id = %s",
            (j_id,),
        )
        row = db.fetchone()
        assert float(row["apc_amount"]) == 2000.0
        assert row["apc_currency"] == "EUR"
        assert row["is_in_doaj"] is True


class TestResetJournalApc:
    def test_resets_only_openalex_journals(self, db):
        j1 = _insert_journal(db, "Nature", openalex_id="S1", apc_amount=3000.0,
                             is_in_doaj=True)
        j2 = _insert_journal(db, "Manual", openalex_id=None, apc_amount=500.0,
                             is_in_doaj=True)

        n = reset_journal_apc(db)

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
    def test_raises_on_self_merge(self, db):
        p_id = _insert_publisher(db, "Elsevier")
        with pytest.raises(RuntimeError, match="lui-même"):
            merge_publishers(db, p_id, p_id)

    def test_transfers_journals_and_deletes_source(self, db):
        target = _insert_publisher(db, "Target")
        source = _insert_publisher(db, "Source")
        j1 = _insert_journal(db, "Journal 1", publisher_id=source)

        merge_publishers(db, target, source)

        db.execute("SELECT id FROM publishers WHERE id = %s", (source,))
        assert db.fetchone() is None  # source supprimée
        db.execute("SELECT publisher_id FROM journals WHERE id = %s", (j1,))
        assert db.fetchone()["publisher_id"] == target

    def test_merges_same_title_journals(self, db):
        """Si cible et source ont un journal de même titre, ils sont fusionnés."""
        target = _insert_publisher(db, "Target")
        source = _insert_publisher(db, "Source")
        jt = _insert_journal(db, "Nature", publisher_id=target, issn="0028-0836")
        js = _insert_journal(db, "Nature", publisher_id=source, eissn="1476-4687")
        _insert_publication(db, journal_id=js)

        merge_publishers(db, target, source)

        # Journal source supprimé
        db.execute("SELECT id FROM journals WHERE id = %s", (js,))
        assert db.fetchone() is None
        # Journal cible enrichi
        db.execute("SELECT issn, eissn FROM journals WHERE id = %s", (jt,))
        row = db.fetchone()
        assert row["issn"] == "0028-0836"
        assert row["eissn"] == "1476-4687"

    def test_raises_on_issn_conflict(self, db):
        target = _insert_publisher(db, "Target")
        source = _insert_publisher(db, "Source")
        _insert_journal(db, "Nature", publisher_id=target, issn="0028-0836")
        _insert_journal(db, "Nature", publisher_id=source, issn="9999-9999")

        with pytest.raises(RuntimeError, match="Conflit issn"):
            merge_publishers(db, target, source)

    def test_enriches_target_flags(self, db):
        """is_predatory = OR logique : vrai si l'une des sources l'était."""
        target = _insert_publisher(db, "Target")
        source = _insert_publisher(db, "Source")
        db.execute("UPDATE publishers SET is_predatory = TRUE WHERE id = %s", (source,))

        merge_publishers(db, target, source)

        db.execute("SELECT is_predatory FROM publishers WHERE id = %s", (target,))
        assert db.fetchone()["is_predatory"] is True

    def test_transfers_openalex_id_when_target_has_none(self, db):
        """Target sans openalex_id, source avec : la cible reçoit celui de la source."""
        target = _insert_publisher(db, "Target", openalex_id=None)
        source = _insert_publisher(db, "Source", openalex_id="P999")
        merge_publishers(db, target, source)
        db.execute("SELECT openalex_id FROM publishers WHERE id = %s", (target,))
        assert db.fetchone()["openalex_id"] == "P999"

    def test_keeps_target_openalex_id_when_both_set(self, db):
        """Si les deux ont un openalex_id, celui de la cible est conservé."""
        target = _insert_publisher(db, "Target", openalex_id="P_TARGET")
        source = _insert_publisher(db, "Source", openalex_id="P_SOURCE")
        merge_publishers(db, target, source)
        db.execute("SELECT openalex_id FROM publishers WHERE id = %s", (target,))
        assert db.fetchone()["openalex_id"] == "P_TARGET"


# ── merge_journals ─────────────────────────────────────────────────

class TestMergeJournals:
    def test_raises_on_self_merge(self, db):
        j_id = _insert_journal(db, "Nature")
        with pytest.raises(RuntimeError, match="lui-même"):
            merge_journals(db, j_id, j_id)

    def test_transfers_publications(self, db):
        target = _insert_journal(db, "Target")
        source = _insert_journal(db, "Source")
        pub_id = _insert_publication(db, journal_id=source)

        merge_journals(db, target, source)

        db.execute("SELECT journal_id FROM publications WHERE id = %s", (pub_id,))
        assert db.fetchone()["journal_id"] == target
        db.execute("SELECT id FROM journals WHERE id = %s", (source,))
        assert db.fetchone() is None

    def test_enriches_target_metadata(self, db):
        target = _insert_journal(db, "Target")  # pas d'ISSN
        source = _insert_journal(db, "Source", issn="1234-5678",
                                 eissn="9999-0000", is_in_doaj=True)

        merge_journals(db, target, source)

        db.execute(
            "SELECT issn, eissn, is_in_doaj FROM journals WHERE id = %s",
            (target,),
        )
        row = db.fetchone()
        assert row["issn"] == "1234-5678"
        assert row["eissn"] == "9999-0000"
        assert row["is_in_doaj"] is True

    def test_does_not_overwrite_existing_fields(self, db):
        """COALESCE : les champs renseignés dans la cible sont préservés."""
        target = _insert_journal(db, "Target", issn="0028-0836")
        source = _insert_journal(db, "Source", issn="1234-5678")

        # ISSN cible existe déjà → COALESCE le garde
        merge_journals(db, target, source)

        db.execute("SELECT issn FROM journals WHERE id = %s", (target,))
        assert db.fetchone()["issn"] == "0028-0836"
