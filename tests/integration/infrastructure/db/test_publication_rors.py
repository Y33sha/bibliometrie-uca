"""Vue matérialisée `publication_rors` : ROR des auteurs d'une publication, ancêtres compris."""

from sqlalchemy import text

from tests.integration.helpers.groups import insert_group
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record
from tests.integration.helpers.structures import refresh_structure_matviews


def _ror_tree(conn) -> None:
    """Un laboratoire `0lab00001` rattaché à son université `0univ0001`."""
    conn.execute(
        text("""
            INSERT INTO ror_organizations (ror_id, name, country_code, types, status) VALUES
                ('0univ0001', 'Université', 'FR', '{education}', 'active'),
                ('0lab00001', 'Laboratoire', 'FR', '{facility}', 'active');
            INSERT INTO ror_relations (parent_ror_id, child_ror_id) VALUES ('0univ0001', '0lab00001');
        """)
    )


def _author(conn, publication: int, source_id: str, ror: str, person: int | None = None) -> None:
    """Un auteur de `publication`, dont la contribution source cite `ror`, rattaché ou non à `person`."""
    record = insert_source_record(conn, publication, source="openalex", source_id=source_id)
    source_contribution = insert_source_contribution(conn, record)
    contribution = insert_group(conn, publication, [(source_contribution, record)])
    conn.execute(
        text("""
            UPDATE contributions SET roles = '{author}', person_id = :p,
                resolution_mode = CASE WHEN CAST(:p AS int) IS NULL THEN NULL ELSE CAST('manual' AS resolution_mode) END
            WHERE id = :c
        """),
        {"p": person, "c": contribution},
    )
    conn.execute(
        text(
            "INSERT INTO source_contribution_rors (source_contribution_id, ror_id) VALUES (:s, :r)"
        ),
        {"s": source_contribution, "r": ror},
    )


def _rors(conn, publication: int) -> set[tuple[str, bool]]:
    refresh_structure_matviews(conn)
    conn.execute(text("REFRESH MATERIALIZED VIEW publication_rors"))
    return {
        (r.ror_id, r.cited)
        for r in conn.execute(
            text("SELECT ror_id, cited FROM publication_rors WHERE publication_id = :p"),
            {"p": publication},
        )
    }


def test_un_ror_cite_entre_avec_ses_ancetres(sa_sync_conn):
    _ror_tree(sa_sync_conn)
    publication = insert_publication(sa_sync_conn)
    _author(sa_sync_conn, publication, "W1", "0lab00001")
    assert _rors(sa_sync_conn, publication) == {("0lab00001", True), ("0univ0001", False)}


def test_une_fausse_entite_ne_compte_pas(sa_sync_conn):
    _ror_tree(sa_sync_conn)
    publication = insert_publication(sa_sync_conn)
    fake = insert_person(sa_sync_conn, "Consortium")
    sa_sync_conn.execute(
        text("UPDATE persons SET exclusion = 'not_a_person' WHERE id = :id"), {"id": fake}
    )
    _author(sa_sync_conn, publication, "W1", "0lab00001", person=fake)
    assert _rors(sa_sync_conn, publication) == set()
