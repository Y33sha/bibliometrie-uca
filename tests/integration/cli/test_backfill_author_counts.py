"""Oneshot `backfill_author_counts` : décomptes des auteurs des enregistrements sources du stock."""

from sqlalchemy import text

from interfaces.cli.oneshot.backfill_author_counts import backfill_batch
from tests.integration.helpers.contributions import upsert_split_contributor_information
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def test_les_decomptes_suivent_les_contributions_sources_d_auteur(sa_sync_conn):
    conn = sa_sync_conn
    source_record = insert_source_record(
        conn, insert_publication(conn), source="hal", source_id="hal-1"
    )
    dupont = upsert_split_contributor_information(conn, "dupont", "jean")
    insert_source_contribution(
        conn, source_record, contributor_information_id=dupont, author_position=0, roles=["author"]
    )
    insert_source_contribution(
        conn, source_record, contributor_information_id=dupont, author_position=1, roles=["author"]
    )
    insert_source_contribution(
        conn,
        source_record,
        contributor_information_id=upsert_split_contributor_information(
            conn, "atlas", "collaboration"
        ),
        author_position=2,
        roles=["author"],
        collective=True,
    )
    insert_source_contribution(
        conn,
        source_record,
        contributor_information_id=upsert_split_contributor_information(conn, "martin", "paul"),
        author_position=None,
        roles=["jury_member"],
    )

    assert backfill_batch(conn, source_record, source_record) == 1
    assert backfill_batch(conn, source_record, source_record) == 0

    counts = conn.execute(
        text("SELECT author_count, distinct_author_count FROM source_records WHERE id = :n"),
        {"n": source_record},
    ).one()
    assert tuple(counts) == (2, 1)
