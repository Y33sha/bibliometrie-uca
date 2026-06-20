"""Intégration : la phase metadata_correction persiste l'effective + le brut réversible."""

from sqlalchemy import text

from application.pipeline.metadata_correction.correct_by_cluster import compute_updates
from application.pipeline.metadata_correction.correct_unary import compute_update
from infrastructure.queries.pipeline.metadata_correction import (
    fetch_doi_cluster_candidates,
    fetch_for_unary_correction,
    persist_corrections,
    persist_doi_corrections,
)


def _seed_journal(conn, journal_type: str) -> int:
    return conn.execute(
        text(
            "INSERT INTO journals (title, title_normalized, journal_type) "
            "VALUES ('J', 'j', :jt) RETURNING id"
        ),
        {"jt": journal_type},
    ).scalar_one()


def _seed_sp(
    conn, *, source_id: str, doc_type: str | None, source="openalex", journal_id=None, urls=None
) -> int:
    return conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, doc_type, journal_id, urls) "
            "VALUES (:src, :sid, 'Un titre', :dt, :jid, :urls) RETURNING id"
        ),
        {"src": source, "sid": source_id, "dt": doc_type, "jid": journal_id, "urls": urls},
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
    assert media_raw == {
        "doc_type": {"raw": "article", "corrected_by": "JOURNAL_TYPE_MEDIA_TO_MEDIA"}
    }

    theses_doc_type, theses_raw = _state(conn, theses_sp)
    assert theses_doc_type == "thesis"
    assert theses_raw == {"doc_type": {"raw": "article", "corrected_by": "THESES_FR_URL_TO_THESIS"}}

    plain_doc_type, plain_raw = _state(conn, plain_sp)
    assert plain_doc_type == "article"
    assert plain_raw == {}


def test_hal_code_mapped_to_canonical(sa_sync_conn):
    conn = sa_sync_conn
    sp = _seed_sp(conn, source_id="hal-1", source="hal", doc_type="ART")
    assert _apply(conn) == 1
    doc_type, raw = _state(conn, sp)
    assert doc_type == "article"  # ART → article par mapping
    assert raw == {"doc_type": {"raw": "ART", "corrected_by": "DOC_TYPE_MAP"}}


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


def test_thesis_with_journal_corrected_and_deconflated(sa_sync_conn):
    conn = sa_sync_conn
    jid = _seed_journal(conn, "journal")
    # DOI d'éditeur (préfixe ≠ registre de thèses) : signe la version publiée → la conflation
    # thèse↔article bascule en `article`. (Avec un DOI ABES ou sans DOI, le type resterait thèse.)
    sp = conn.execute(
        text(
            "INSERT INTO source_publications "
            "(source, source_id, title, doc_type, doi, journal_id, external_ids) "
            "VALUES ('openalex', 'W-conflation', 'T', 'thesis', '10.1016/j.ex.2020.01.001', :jid, "
            '\'{"nnt": "2020CLFAC001", "hal_id": ["tel-01", "hal-99"]}\'::jsonb) RETURNING id'
        ),
        {"jid": jid},
    ).scalar_one()

    assert _apply(conn) == 1
    row = conn.execute(
        text("SELECT doc_type, external_ids, raw_metadata FROM source_publications WHERE id = :id"),
        {"id": sp},
    ).one()
    assert row.doc_type == "article"  # mistype corrigé
    assert row.external_ids == {"hal_id": ["hal-99"]}  # nnt + tel- retirés, hal- gardé
    assert row.raw_metadata["doc_type"]["corrected_by"] == "THESIS_WITH_JOURNAL_TO_ARTICLE"
    assert row.raw_metadata["external_ids"]["corrected_by"] == "THESIS_WITH_JOURNAL_TO_ARTICLE"
    # Réversibilité : le brut external_ids est reconstructible.
    raw_nnt = conn.execute(
        text(
            "SELECT raw_metadata->'external_ids'->'raw'->>'nnt' FROM source_publications WHERE id = :id"
        ),
        {"id": sp},
    ).scalar_one()
    assert raw_nnt == "2020CLFAC001"


def test_expired_embargo_promoted_to_green(sa_sync_conn):
    conn = sa_sync_conn
    # `embargo_expired` est calculé au fetch (`embargo_until <= current_date`) ; date de levée
    # passée ⇒ la règle promeut `embargoed → green`. (Règle agnostique de la source.)
    sp = conn.execute(
        text(
            "INSERT INTO source_publications "
            "(source, source_id, title, doc_type, oa_status, embargo_until) "
            "VALUES ('openalex', 'W-emb-past', 'T', 'article', 'embargoed', current_date - 1) "
            "RETURNING id"
        )
    ).scalar_one()
    assert _apply(conn) == 1
    row = conn.execute(
        text("SELECT oa_status::text AS oa, raw_metadata FROM source_publications WHERE id = :id"),
        {"id": sp},
    ).one()
    assert row.oa == "green"
    assert row.raw_metadata["oa_status"] == {
        "raw": "embargoed",
        "corrected_by": "EMBARGO_EXPIRED_TO_GREEN",
    }


def test_active_embargo_not_promoted(sa_sync_conn):
    conn = sa_sync_conn
    # Date de levée future ⇒ `embargo_expired` faux ⇒ pas de promotion.
    sp = conn.execute(
        text(
            "INSERT INTO source_publications "
            "(source, source_id, title, doc_type, oa_status, embargo_until) "
            "VALUES ('openalex', 'W-emb-future', 'T', 'article', 'embargoed', current_date + 365) "
            "RETURNING id"
        )
    ).scalar_one()
    assert _apply(conn) == 0
    oa = conn.execute(
        text("SELECT oa_status::text FROM source_publications WHERE id = :id"), {"id": sp}
    ).scalar_one()
    assert oa == "embargoed"


# ── Sous-étape cluster : ouvrage/chapitre au même DOI ──


def _seed_typed_sp(conn, *, source_id, doc_type, doi, title="T", title_normalized="t"):
    return conn.execute(
        text(
            "INSERT INTO source_publications "
            "(source, source_id, title, title_normalized, doc_type, doi) "
            "VALUES ('openalex', :sid, :title, :tn, :dt, :doi) RETURNING id"
        ),
        {"sid": source_id, "dt": doc_type, "doi": doi, "title": title, "tn": title_normalized},
    ).scalar_one()


def _apply_cluster(conn) -> int:
    rows = fetch_doi_cluster_candidates(conn)
    return persist_doi_corrections(conn, compute_updates(rows))


def test_chapter_loses_doi_of_its_book(sa_sync_conn):
    conn = sa_sync_conn
    book = _seed_typed_sp(conn, source_id="b1", doc_type="book", doi="10.1/x")
    chapter = _seed_typed_sp(conn, source_id="c1", doc_type="book_chapter", doi="10.1/x")

    assert _apply_cluster(conn) == 1  # seul le chapitre

    book_doi, _ = _state(conn, book)
    # le book garde son DOI
    assert (
        conn.execute(
            text("SELECT doi FROM source_publications WHERE id = :id"), {"id": book}
        ).scalar_one()
        == "10.1/x"
    )
    chap_doi = conn.execute(
        text("SELECT doi FROM source_publications WHERE id = :id"), {"id": chapter}
    ).scalar_one()
    assert chap_doi is None
    chap_raw = conn.execute(
        text("SELECT raw_metadata FROM source_publications WHERE id = :id"), {"id": chapter}
    ).scalar_one()
    assert chap_raw == {"doi": {"raw": "10.1/x", "corrected_by": "OUVRAGE_VS_CHAPITRE"}}

    # Réversibilité : le DOI brut du chapitre reste reconstructible.
    reconstructed = conn.execute(
        text(
            "SELECT COALESCE(raw_metadata->'doi'->>'raw', doi) "
            "FROM source_publications WHERE id = :id"
        ),
        {"id": chapter},
    ).scalar_one()
    assert reconstructed == "10.1/x"


def test_idempotent_and_self_heals_when_book_retyped(sa_sync_conn):
    conn = sa_sync_conn
    book = _seed_typed_sp(conn, source_id="b1", doc_type="book", doi="10.1/x")
    chapter = _seed_typed_sp(conn, source_id="c1", doc_type="book_chapter", doi="10.1/x")
    assert _apply_cluster(conn) == 1
    assert _apply_cluster(conn) == 0  # idempotent

    # L'ouvrage est retypé (n'est plus un book) : le chapitre récupère son DOI.
    conn.execute(
        text("UPDATE source_publications SET doc_type = 'article' WHERE id = :id"), {"id": book}
    )
    assert _apply_cluster(conn) == 1
    chap_doi = conn.execute(
        text("SELECT doi, raw_metadata FROM source_publications WHERE id = :id"), {"id": chapter}
    ).one()
    assert chap_doi.doi == "10.1/x"
    assert chap_doi.raw_metadata == {}


def test_chapters_same_title_untouched(sa_sync_conn):
    # Même chapitre (titre normalisé identique) sous un DOI : pas de conflit.
    conn = sa_sync_conn
    _seed_typed_sp(
        conn, source_id="c1", doc_type="book_chapter", doi="10.1/y", title_normalized="introduction"
    )
    _seed_typed_sp(
        conn, source_id="c2", doc_type="book_chapter", doi="10.1/y", title_normalized="introduction"
    )
    assert _apply_cluster(conn) == 0


def test_chapters_distinct_titles_both_lose_doi(sa_sync_conn):
    # Deux chapitres réellement distincts au même DOI (sans ouvrage) → tous deux perdent le DOI.
    conn = sa_sync_conn
    c1 = _seed_typed_sp(
        conn,
        source_id="c1",
        doc_type="book_chapter",
        doi="10.1/z",
        title_normalized="geographie de l environnement",
    )
    c2 = _seed_typed_sp(
        conn,
        source_id="c2",
        doc_type="book_chapter",
        doi="10.1/z",
        title_normalized="nommer et representer les processus biophysiques",
    )
    assert _apply_cluster(conn) == 2
    for sp in (c1, c2):
        row = conn.execute(
            text("SELECT doi, raw_metadata FROM source_publications WHERE id = :id"), {"id": sp}
        ).one()
        assert row.doi is None
        assert row.raw_metadata["doi"]["corrected_by"] == "CHAPITRES_TITRES_DIFFERENTS"


def test_chapters_number_prefix_same_chapter_untouched(sa_sync_conn):
    # « chapitre 14 X » vs « X » : même chapitre après nettoyage → pas de conflit.
    conn = sa_sync_conn
    _seed_typed_sp(
        conn,
        source_id="c1",
        doc_type="book_chapter",
        doi="10.1/w",
        title_normalized="chapitre 14 les limnosystemes",
    )
    _seed_typed_sp(
        conn,
        source_id="c2",
        doc_type="book_chapter",
        doi="10.1/w",
        title_normalized="les limnosystemes",
    )
    assert _apply_cluster(conn) == 0
