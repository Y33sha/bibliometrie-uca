"""Oneshot `restore_primary_identifiers` : identifiant primaire écrit d'après le `source_id`, mise en file pour la réconciliation."""

from sqlalchemy import text

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from infrastructure.db.queues import Queue
from interfaces.cli.oneshot.restore_primary_identifiers import restore_primary_identifiers
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.sources import insert_source_record


def _primary(conn, source_record_id: int) -> list[tuple[str, str]]:
    return [
        (r.id_type, r.id_value)
        for r in conn.execute(
            text(
                "SELECT id_type::text, id_value FROM source_record_identifiers"
                " WHERE source_record_id = :id AND role = 'primary'"
            ),
            {"id": source_record_id},
        )
    ]


def test_ecrit_l_identifiant_primaire_d_apres_le_source_id(sa_sync_conn):
    crossref = insert_source_record(sa_sync_conn, source="crossref", source_id="10.1016/J.X.1")
    hal = insert_source_record(sa_sync_conn, source="hal", source_id="hal-04955166")
    defended = insert_source_record(sa_sync_conn, source="theses", source_id="2019CLFAC001")
    ongoing = insert_source_record(sa_sync_conn, source="theses", source_id="s123456")
    clear(sa_sync_conn, Queue.SOURCE_RECORD_KEYS)

    restore_primary_identifiers(sa_sync_conn)

    assert _primary(sa_sync_conn, crossref) == [("doi", "10.1016/j.x.1")]
    assert _primary(sa_sync_conn, hal) == [("hal_id", "hal-04955166")]
    assert _primary(sa_sync_conn, defended) == [("nnt", "2019CLFAC001")]
    assert _primary(sa_sync_conn, ongoing) == []
    assert queued(sa_sync_conn, Queue.SOURCE_RECORD_KEYS) == {crossref, hal, defended}


def test_laisse_un_identifiant_primaire_retire(sa_sync_conn):
    """Un DOI primaire retiré par une correction reste retiré."""
    record = insert_source_record(
        sa_sync_conn,
        source="crossref",
        source_id="10.1016/j.x.1",
        identifiers=[
            SourceIdentifier(
                SourceIdentifierType.DOI,
                "10.1016/j.x.1",
                SourceIdentifierRole.PRIMARY,
                removed_by="RULE",
            )
        ],
    )
    clear(sa_sync_conn, Queue.SOURCE_RECORD_KEYS)

    restore_primary_identifiers(sa_sync_conn)

    assert _primary(sa_sync_conn, record) == [("doi", "10.1016/j.x.1")]
    assert queued(sa_sync_conn, Queue.SOURCE_RECORD_KEYS) == set()


def test_dry_run_compte_sans_ecrire(sa_sync_conn):
    record = insert_source_record(sa_sync_conn, source="datacite", source_id="10.5281/zenodo.1")

    counts = restore_primary_identifiers(sa_sync_conn, dry_run=True)

    assert counts["datacite, identifiant primaire écrit"] == 1
    assert _primary(sa_sync_conn, record) == []
