"""Attributs des contributions recomposés depuis leurs contributions sources, pour les contributions en file (`AuthorGroupingStore.propagate_attributes`)."""

from sqlalchemy import text

from infrastructure.db.queues import Queue, enqueue
from pipeline.transformation.publications.author_grouping.store import AuthorGroupingStore
from tests.integration.helpers.alignment import align_source_contributions
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _member(conn, publication, source, *, corresponding, roles, evidence):
    source_record = insert_source_record(
        conn, publication, source=source, source_id=f"{source}-{publication}"
    )
    source_contribution = insert_source_contribution(
        conn,
        source_record,
        source=source,
        raw_author_name="Jean Martin",
        author_name_normalized="jean martin",
        roles=roles,
    )
    conn.execute(
        text(
            "UPDATE source_contributions SET is_corresponding = :c,"
            " perimeter_evidence = CAST(:e AS perimeter_evidence[]) WHERE id = :s"
        ),
        {"c": corresponding, "e": evidence, "s": source_contribution},
    )
    return source_contribution, source_record


def _contribution_of_two(conn) -> int:
    publication = insert_publication(conn)
    return align_source_contributions(
        conn,
        publication,
        [
            _member(
                conn,
                publication,
                "hal",
                corresponding=False,
                roles=["author"],
                evidence="{hal_structure}",
            ),
            _member(
                conn,
                publication,
                "openalex",
                corresponding=True,
                roles=["editor"],
                evidence="{address,ror}",
            ),
        ],
    )


def _attributes(conn, contribution):
    return conn.execute(
        text(
            "SELECT author_positions::text[] AS positions, roles,"
            " perimeter_evidence::text[] AS evidence, in_perimeter"
            " FROM contributions WHERE id = :g"
        ),
        {"g": contribution},
    ).one()


def test_les_attributs_de_la_contribution_reunissent_ceux_de_ses_contributions_sources(
    sa_sync_conn,
):
    conn = sa_sync_conn
    contribution = _contribution_of_two(conn)
    store = AuthorGroupingStore(conn)

    assert store.propagate_attributes() == (1, 1)

    row = _attributes(conn, contribution)
    # Seul auteur de la liste HAL, la contribution en est le premier et le dernier auteur.
    assert (row.positions, row.roles, row.evidence, row.in_perimeter) == (
        ["corresponding", "first", "last"],
        ["author", "editor"],
        ["address", "hal_structure", "ror"],
        True,
    )
    assert queued(conn, Queue.CONTRIBUTION_ATTRIBUTES) == set()
    assert store.propagate_attributes() == (0, 0)


def _leave_perimeter(conn, contribution, mode):
    """Rattache la contribution du périmètre à une personne selon `mode`, puis retire les indices de ses contributions sources et la remet en file de recomposition."""
    AuthorGroupingStore(conn).propagate_attributes()
    person = insert_person(conn, "Martin", first_name="Jean")
    conn.execute(
        text(
            "UPDATE contributions SET person_id = :p,"
            " resolution_mode = CAST(:m AS resolution_mode) WHERE id = :g"
        ),
        {"p": person, "m": mode, "g": contribution},
    )
    conn.execute(
        text(
            "UPDATE source_contributions SET perimeter_evidence = '{}' WHERE id IN"
            " (SELECT source_contribution_id FROM aligned_source_contributions"
            " WHERE contribution_id = :g)"
        ),
        {"g": contribution},
    )
    clear(conn, Queue.CONTRIBUTION_RESOLUTION)
    enqueue(conn, Queue.CONTRIBUTION_ATTRIBUTES, "SELECT CAST(:g AS integer)", {"g": contribution})
    AuthorGroupingStore(conn).propagate_attributes()


def test_une_contribution_rattachee_qui_quitte_le_perimetre_est_a_redecider(sa_sync_conn):
    conn = sa_sync_conn
    contribution = _contribution_of_two(conn)

    _leave_perimeter(conn, contribution, "name")

    assert not _attributes(conn, contribution).in_perimeter
    assert queued(conn, Queue.CONTRIBUTION_RESOLUTION) == {contribution}


def test_une_contribution_epinglee_qui_quitte_le_perimetre_reste_hors_file(sa_sync_conn):
    conn = sa_sync_conn
    contribution = _contribution_of_two(conn)

    _leave_perimeter(conn, contribution, "manual")

    assert queued(conn, Queue.CONTRIBUTION_RESOLUTION) == set()


def test_une_contribution_hors_file_garde_ses_attributs(sa_sync_conn):
    conn = sa_sync_conn
    contribution = _contribution_of_two(conn)
    clear(conn, Queue.CONTRIBUTION_ATTRIBUTES)

    assert AuthorGroupingStore(conn).propagate_attributes() == (0, 0)

    assert _attributes(conn, contribution).roles is None
