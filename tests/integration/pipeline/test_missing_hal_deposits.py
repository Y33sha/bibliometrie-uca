"""Dépôts HAL introuvables retirés des enregistrements sources, et enregistrements sources écartés de la réconciliation (`is_matchable`)."""

import logging

from sqlalchemy import text

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from infrastructure.db.queues import Queue
from pipeline.transformation.publications.reconciliation import reconcile
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.publications_phase import apply_metadata_corrections
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.sources import insert_source_record, secondary_identifiers
from tests.integration.helpers.staging import insert_failed_lookup

_MISSING = "hal-03178520"
_MISSING_URL = f"https://hal.science/{_MISSING}"


def _state(conn, source_record_id):
    return conn.execute(
        text(
            "SELECT ARRAY(SELECT i.id_value FROM source_record_identifiers i"
            " WHERE i.source_record_id = sr.id AND i.id_type = 'hal_id' AND i.removed_by IS NULL"
            " ORDER BY i.id_value) AS hal_ids, urls, is_matchable, publication_id"
            " FROM source_records sr"
            " WHERE id = :id"
        ),
        {"id": source_record_id},
    ).one()


def _locations(conn, source_record_id) -> list[str]:
    return list(
        conn.execute(
            text(
                "SELECT url FROM source_record_locations WHERE source_record_id = :id ORDER BY url"
            ),
            {"id": source_record_id},
        ).scalars()
    )


def _seed_openalex(conn, publication_id=None, *, hal_ids=(_MISSING,), urls=(_MISSING_URL,)):
    source_record_id = insert_source_record(
        conn,
        publication_id,
        source="openalex",
        source_id="W4287257393",
        title="Puzzle with the precession of the neutron spin",
        title_normalized="puzzle with the precession of the neutron spin",
        publication_year=2021,
        doc_type="preprint",
        identifiers=[
            SourceIdentifier(SourceIdentifierType.HAL_ID, h, SourceIdentifierRole.SECONDARY)
            for h in hal_ids
        ],
        urls=list(urls),
    )
    for url in urls:
        conn.execute(
            text("INSERT INTO source_record_locations (source_record_id, url) VALUES (:id, :url)"),
            {"id": source_record_id, "url": url},
        )
    return source_record_id


def test_enregistrement_openalex_du_seul_depot_introuvable_est_ecarte(sa_sync_conn):
    """Régression : l'enregistrement OpenAlex W4287257393 citait le seul dépôt hal-03178520, introuvable dans HAL, et formait une publication à part."""
    conn = sa_sync_conn
    publication = insert_publication(conn)
    record = _seed_openalex(conn, publication)
    insert_failed_lookup(conn, id_type="hal_id", id_value=_MISSING)

    apply_metadata_corrections(conn)

    state = _state(conn, record)
    assert state.hal_ids == []
    assert state.urls is None
    assert not state.is_matchable
    assert _locations(conn, record) == []

    reconcile(conn, logging.getLogger("test"))
    assert _state(conn, record).publication_id is None
    assert (
        conn.execute(
            text("SELECT count(*) FROM publications WHERE id = :id"), {"id": publication}
        ).scalar_one()
        == 0
    )


def test_enregistrement_qui_garde_un_lien_reste_dans_la_reconciliation(sa_sync_conn):
    conn = sa_sync_conn
    kept_url = "https://hal.science/hal-03263588/document"
    record = _seed_openalex(conn, hal_ids=(_MISSING, "hal-03263588"), urls=(_MISSING_URL, kept_url))
    insert_failed_lookup(conn, id_type="hal_id", id_value=_MISSING)

    apply_metadata_corrections(conn)

    state = _state(conn, record)
    assert state.hal_ids == ["hal-03263588"]
    assert state.urls == [kept_url]
    assert state.is_matchable
    assert _locations(conn, record) == [kept_url]


def test_depot_retrouve_reintegre_l_enregistrement(sa_sync_conn):
    conn = sa_sync_conn
    record = _seed_openalex(conn)
    insert_failed_lookup(conn, id_type="hal_id", id_value=_MISSING)
    apply_metadata_corrections(conn)
    clear(conn, Queue.SOURCE_RECORD_KEYS)

    conn.execute(text("DELETE FROM failed_lookups"))
    apply_metadata_corrections(conn)

    state = _state(conn, record)
    assert state.hal_ids == [_MISSING]
    assert state.urls == [_MISSING_URL]
    assert state.is_matchable
    assert record in queued(conn, Queue.SOURCE_RECORD_KEYS)


def test_enregistrement_scanr_issu_d_un_depot_introuvable_est_ecarte(sa_sync_conn):
    conn = sa_sync_conn
    record = insert_source_record(
        conn,
        source="scanr",
        source_id="halhal-05524892",
        title="T",
        doi="10.1/x",
        identifiers=secondary_identifiers({"hal_id": ["hal-05524892"]}),
    )
    insert_failed_lookup(conn, id_type="hal_id", id_value="hal-05524892")

    apply_metadata_corrections(conn)

    assert not _state(conn, record).is_matchable


def test_paratexte_et_gresis_sont_ecartes(sa_sync_conn):
    conn = sa_sync_conn
    paratext = insert_source_record(
        conn,
        source="crossref",
        source_id="10.1/front",
        title="Front Matter",
        doi="10.1/front",
        title_normalized="front matter",
    )
    gresis = insert_source_record(
        conn,
        source="datacite",
        source_id="10.60692/m2raz-tjw54",
        title="T",
        doi="10.60692/m2raz-tjw54",
    )
    clear(conn, Queue.SOURCE_RECORD_KEYS)

    apply_metadata_corrections(conn)

    assert not _state(conn, paratext).is_matchable
    assert not _state(conn, gresis).is_matchable
    assert {paratext, gresis} <= queued(conn, Queue.SOURCE_RECORD_KEYS)
