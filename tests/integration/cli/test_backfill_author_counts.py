"""Oneshot `backfill_author_counts` : décomptes des auteurs des enregistrements sources de brevet."""

from sqlalchemy import text

from interfaces.cli.oneshot.backfill_author_counts import backfill_patents
from tests.integration.helpers.contributions import upsert_split_contributor_information
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _counts(conn, source_record: int) -> tuple[int, int]:
    return tuple(
        conn.execute(
            text("SELECT author_count, distinct_author_count FROM source_records WHERE id = :n"),
            {"n": source_record},
        ).one()
    )


def test_les_inventeurs_d_un_brevet_comptent_comme_auteurs(sa_sync_conn):
    conn = sa_sync_conn
    patent = insert_source_record(
        conn,
        insert_publication(conn),
        source="scanr_patents",
        source_id="family-1",
        doc_type="patent",
    )
    dupont = upsert_split_contributor_information(conn, "dupont", "jean")
    insert_source_contribution(
        conn, patent, contributor_information_id=dupont, author_position=0, roles=["inventor"]
    )
    insert_source_contribution(
        conn, patent, contributor_information_id=dupont, author_position=1, roles=["inventor"]
    )
    insert_source_contribution(
        conn,
        patent,
        contributor_information_id=upsert_split_contributor_information(
            conn, "atlas", "collaboration"
        ),
        author_position=2,
        roles=["inventor"],
        collective=True,
    )
    article = insert_source_record(conn, insert_publication(conn), source="hal", source_id="hal-1")
    insert_source_contribution(conn, article, contributor_information_id=dupont, roles=["author"])

    assert backfill_patents(conn) == 1
    assert backfill_patents(conn) == 0

    assert _counts(conn, patent) == (2, 1)
    assert _counts(conn, article) == (0, 0)
