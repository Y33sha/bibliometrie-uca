"""Intégration : la phase metadata_correction persiste l'effective + le brut réversible."""

from sqlalchemy import text

from application.pipeline.metadata_correction.correct_unary import compute_update
from infrastructure.queries.pipeline.metadata_correction import (
    fetch_for_unary_correction,
    persist_corrections,
)


def _seed_journal(conn, journal_type: str) -> int:
    return conn.execute(
        text(
            "INSERT INTO journals (title, title_normalized, journal_type) "
            "VALUES ('J', 'j', :jt) RETURNING id"
        ),
        {"jt": journal_type},
    ).scalar_one()


def _seed_sp(conn, *, source_id: str, doc_type: str | None, journal_id=None, urls=None) -> int:
    return conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, doc_type, journal_id, urls) "
            "VALUES ('openalex', :sid, 'Un titre', :dt, :jid, :urls) RETURNING id"
        ),
        {"sid": source_id, "dt": doc_type, "jid": journal_id, "urls": urls},
    ).scalar_one()


def _apply(conn) -> int:
    """Joue la passe unaire sans committer (transaction de test rollbackée)."""
    rows = fetch_for_unary_correction(conn)
    updates = [u for r in rows if (u := compute_update(r)) is not None]
    return persist_corrections(conn, updates)


def _state(conn, sp_id: int) -> tuple:
    return conn.execute(
        text("SELECT doc_type, raw_metadata FROM source_publications WHERE id = :id"),
        {"id": sp_id},
    ).one()


def test_journal_media_and_theses_url_corrected_plain_untouched(sa_sync_conn):
    conn = sa_sync_conn
    media_journal = _seed_journal(conn, "media")
    media_sp = _seed_sp(conn, source_id="W_media", doc_type="article", journal_id=media_journal)
    theses_sp = _seed_sp(
        conn, source_id="W_theses", doc_type="article", urls=["https://theses.fr/2020ABCD"]
    )
    plain_sp = _seed_sp(conn, source_id="W_plain", doc_type="article")

    n = _apply(conn)
    assert n == 2  # media + theses corrigées, plain non

    media_doc_type, media_raw = _state(conn, media_sp)
    assert media_doc_type == "media"
    assert media_raw == {"doc_type": {"raw": "article", "by": "JOURNAL_TYPE_MEDIA_TO_MEDIA"}}

    theses_doc_type, theses_raw = _state(conn, theses_sp)
    assert theses_doc_type == "thesis"
    assert theses_raw == {"doc_type": {"raw": "article", "by": "THESES_FR_URL_TO_THESIS"}}

    plain_doc_type, plain_raw = _state(conn, plain_sp)
    assert plain_doc_type == "article"
    assert plain_raw == {}


def test_reversibility_invariant(sa_sync_conn):
    conn = sa_sync_conn
    media_journal = _seed_journal(conn, "media")
    _seed_sp(conn, source_id="W_media", doc_type="article", journal_id=media_journal)
    _apply(conn)

    # COALESCE(raw_metadata->'doc_type'->>'raw', doc_type) reconstruit le brut d'origine.
    reconstructed = conn.execute(
        text(
            "SELECT COALESCE(raw_metadata->'doc_type'->>'raw', doc_type) "
            "FROM source_publications WHERE source_id = 'W_media'"
        )
    ).scalar_one()
    assert reconstructed == "article"


def test_idempotent_second_run_changes_nothing(sa_sync_conn):
    conn = sa_sync_conn
    media_journal = _seed_journal(conn, "media")
    _seed_sp(conn, source_id="W_media", doc_type="article", journal_id=media_journal)
    _seed_sp(conn, source_id="W_theses", doc_type="article", urls=["https://theses.fr/2020ABCD"])

    assert _apply(conn) == 2
    assert _apply(conn) == 0  # rien à recorriger


def test_self_heals_when_journal_no_longer_media(sa_sync_conn):
    conn = sa_sync_conn
    media_journal = _seed_journal(conn, "media")
    sp = _seed_sp(conn, source_id="W_media", doc_type="article", journal_id=media_journal)
    assert _apply(conn) == 1
    assert _state(conn, sp)[0] == "media"

    # Le journal change de type : la règle ne s'applique plus, le brut doit revenir.
    conn.execute(
        text("UPDATE journals SET journal_type = 'journal' WHERE id = :id"),
        {"id": media_journal},
    )
    assert _apply(conn) == 1
    doc_type, raw = _state(conn, sp)
    assert doc_type == "article"
    assert raw == {}
