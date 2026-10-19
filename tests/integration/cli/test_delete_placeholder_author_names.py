"""Oneshot `delete_placeholder_author_names` : signatures du stock dont le nom tient lieu de nom absent."""

from sqlalchemy import text

from interfaces.cli.oneshot.delete_placeholder_author_names import (
    delete,
    placeholder_signatures,
)
from tests.integration.helpers.authorships import upsert_split_identity
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_publication


def test_seules_les_signatures_au_nom_absent_sont_supprimees(sa_sync_conn):
    conn = sa_sync_conn
    publication = insert_publication(conn)
    conn.execute(
        text("UPDATE publications SET authorships_dirty = false WHERE id = :p"), {"p": publication}
    )
    notice = insert_source_publication(conn, publication, source="datacite", source_id="10.1/x")
    signatures = [
        insert_signature(
            conn,
            notice,
            source="datacite",
            author_position=position,
            identity_id=upsert_split_identity(conn, last.lower(), first.lower()),
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

    ids, notices = placeholder_signatures(conn)
    assert sorted(ids) == sorted(signatures[:2])
    delete(conn, ids, notices)

    remaining = conn.execute(
        text("SELECT id FROM source_authorships WHERE source_publication_id = :n"), {"n": notice}
    ).scalars()
    assert sorted(remaining) == sorted(signatures[2:])
    assert conn.execute(
        text("SELECT authorships_dirty FROM publications WHERE id = :p"), {"p": publication}
    ).scalar_one()
