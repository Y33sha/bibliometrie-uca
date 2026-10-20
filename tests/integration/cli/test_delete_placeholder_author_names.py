"""Oneshot `delete_placeholder_author_names` : contributions sources du stock dont le nom tient lieu de nom absent."""

from sqlalchemy import text

from interfaces.cli.oneshot.delete_placeholder_author_names import (
    delete,
    placeholder_source_contributions,
)
from tests.integration.helpers.contributions import upsert_split_contributor_information
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def test_seules_les_contributions_sources_au_nom_absent_sont_supprimees(sa_sync_conn):
    conn = sa_sync_conn
    publication = insert_publication(conn)
    conn.execute(
        text("UPDATE publications SET contributions_dirty = false WHERE id = :p"),
        {"p": publication},
    )
    source_record = insert_source_record(conn, publication, source="datacite", source_id="10.1/x")
    source_contributions = [
        insert_source_contribution(
            conn,
            source_record,
            source="datacite",
            author_position=position,
            contributor_information_id=upsert_split_contributor_information(
                conn, last.lower(), first.lower()
            ),
            roles=["author"],
            **name,
        )
        for position, (name, last, first) in enumerate(
            (
                ({"raw_author_name": "(:Unap)"}, "unap", ""),
                ({"raw_last_name": "None", "raw_first_name": "None"}, "none", "none"),
                ({"raw_last_name": "None", "raw_first_name": "Paolo"}, "none", "paolo"),
                ({"raw_author_name": "Unal, Guillaume"}, "unal", "guillaume"),
            )
        )
    ]

    ids, source_records = placeholder_source_contributions(conn)
    assert sorted(ids) == sorted(source_contributions[:2])
    delete(conn, ids, source_records)

    remaining = conn.execute(
        text("SELECT id FROM source_contributions WHERE source_record_id = :n"),
        {"n": source_record},
    ).scalars()
    assert sorted(remaining) == sorted(source_contributions[2:])
    assert conn.execute(
        text("SELECT contributions_dirty FROM publications WHERE id = :p"), {"p": publication}
    ).scalar_one()
