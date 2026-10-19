"""Oneshot `regroup_neutralized_identifiers` : publications à regrouper après la lecture des identifiants neutralisés."""

from sqlalchemy import text

from interfaces.cli.oneshot.regroup_neutralized_identifiers import mark
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_publication


def _publication(conn, *, notices, neutralized):
    """Publication de `notices` notices, non marquée ; sa première notice a une signature d'ORCID neutralisé si `neutralized`."""
    publication = insert_publication(conn)
    conn.execute(
        text("UPDATE publications SET authorships_dirty = false WHERE id = :p"), {"p": publication}
    )
    for rank in range(notices):
        notice = insert_source_publication(
            conn, publication, source="crossref", source_id=f"c-{publication}-{rank}"
        )
        insert_signature(
            conn,
            notice,
            source="crossref",
            author_name_normalized="jean dupont",
            person_identifiers={"orcid": "0000-0001-2345-6789"},
            neutralized_identifiers={"orcid": "shared"} if neutralized and rank == 0 else None,
        )
    return publication


def _dirty(conn, publication):
    return conn.execute(
        text("SELECT authorships_dirty FROM publications WHERE id = :p"), {"p": publication}
    ).scalar_one()


def test_seules_les_publications_a_plusieurs_notices_et_identifiant_neutralise_sont_marquees(
    sa_sync_conn,
):
    visee = _publication(sa_sync_conn, notices=2, neutralized=True)
    une_notice = _publication(sa_sync_conn, notices=1, neutralized=True)
    sans_neutralisation = _publication(sa_sync_conn, notices=2, neutralized=False)

    mark(sa_sync_conn)

    assert (
        _dirty(sa_sync_conn, visee),
        _dirty(sa_sync_conn, une_notice),
        _dirty(sa_sync_conn, sans_neutralisation),
    ) == (True, False, False)
