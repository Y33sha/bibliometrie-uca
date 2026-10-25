"""Vue matérialisée `publication_rors` : ROR des auteurs d'une publication, ancêtres compris."""

from sqlalchemy import text

from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.rors import insert_author, insert_ror_tree, refresh_publication_rors


def _rors(conn, publication: int) -> set[tuple[str, bool]]:
    refresh_publication_rors(conn)
    return {
        (r.ror_id, r.cited)
        for r in conn.execute(
            text("SELECT ror_id, cited FROM publication_rors WHERE publication_id = :p"),
            {"p": publication},
        )
    }


def test_un_ror_cite_entre_avec_ses_ancetres(sa_sync_conn):
    insert_ror_tree(sa_sync_conn)
    publication = insert_publication(sa_sync_conn)
    insert_author(sa_sync_conn, publication, "W1", "0lab00001")
    assert _rors(sa_sync_conn, publication) == {("0lab00001", True), ("0univ0001", False)}


def test_une_fausse_entite_ne_compte_pas(sa_sync_conn):
    insert_ror_tree(sa_sync_conn)
    publication = insert_publication(sa_sync_conn)
    fake = insert_person(sa_sync_conn, "Consortium")
    sa_sync_conn.execute(
        text("UPDATE persons SET exclusion = 'not_a_person' WHERE id = :id"), {"id": fake}
    )
    insert_author(sa_sync_conn, publication, "W1", "0lab00001", person=fake)
    assert _rors(sa_sync_conn, publication) == set()
