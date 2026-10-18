"""Oneshot `mark_collective_signatures` : marque collective une signature et met sa publication à regrouper."""

from sqlalchemy import text

from interfaces.cli.oneshot.mark_collective_signatures import mark_collective
from tests.integration.helpers.authorships import upsert_split_identity
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_publication


def test_la_publication_d_une_signature_marquee_est_a_regrouper(sa_sync_conn):
    conn = sa_sync_conn
    publication = insert_publication(conn)
    conn.execute(
        text("UPDATE publications SET authorships_dirty = false WHERE id = :p"), {"p": publication}
    )
    notice = insert_source_publication(conn, publication, source="openalex", source_id="W1")
    signature = insert_signature(
        conn,
        notice,
        identity_id=upsert_split_identity(conn, "al", "et"),
        author_position=3,
        roles=["author"],
    )

    mark_collective(conn, [signature])

    assert conn.execute(
        text("SELECT collective FROM source_authorships WHERE id = :s"), {"s": signature}
    ).scalar_one()
    assert conn.execute(
        text("SELECT authorships_dirty FROM publications WHERE id = :p"), {"p": publication}
    ).scalar_one()
