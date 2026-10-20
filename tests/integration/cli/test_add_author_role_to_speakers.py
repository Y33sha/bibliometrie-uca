"""Oneshot `add_author_role_to_speakers` : le rôle `author` complète les signatures `speaker`."""

from sqlalchemy import text

from interfaces.cli.oneshot.add_author_role_to_speakers import add_author_role
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_record


def _roles(conn, signature: int) -> list[str]:
    return conn.execute(
        text("SELECT roles FROM source_contributions WHERE id = :i"), {"i": signature}
    ).scalar_one()


def test_l_orateur_devient_aussi_auteur_et_sa_publication_est_a_regrouper(sa_sync_conn):
    conn = sa_sync_conn
    speaker_pub = insert_publication(conn)
    other_pub = insert_publication(conn)
    speaker = insert_signature(
        conn,
        insert_source_record(conn, speaker_pub, source="hal", source_id="hal-1"),
        roles=["speaker"],
    )
    both = insert_signature(
        conn,
        insert_source_record(conn, other_pub, source="hal", source_id="hal-2"),
        roles=["author", "speaker"],
    )
    conn.execute(text("UPDATE publications SET contributions_dirty = false"))

    assert add_author_role(conn) == (1, 1)

    assert _roles(conn, speaker) == ["author", "speaker"]
    assert _roles(conn, both) == ["author", "speaker"]
    dirty = dict(conn.execute(text("SELECT id, contributions_dirty FROM publications")).all())
    assert dirty[speaker_pub] is True
    assert dirty[other_pub] is False
