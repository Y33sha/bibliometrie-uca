"""Attributs des contributions recomposés depuis leurs contributions sources, pour les contributions en file (`AuthorGroupingStore.propagate_attributes`)."""

from sqlalchemy import text

from infrastructure.db.queues import Queue
from pipeline.transformation.publications.author_grouping.store import AuthorGroupingStore
from tests.integration.helpers.groups import insert_group
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


def _group_of_two(conn) -> int:
    publication = insert_publication(conn)
    return insert_group(
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


def _attributes(conn, group):
    return conn.execute(
        text(
            "SELECT is_corresponding, roles, perimeter_evidence::text[] AS evidence, in_perimeter"
            " FROM contributions WHERE id = :g"
        ),
        {"g": group},
    ).one()


def test_les_attributs_de_la_contribution_reunissent_ceux_de_ses_contributions_sources(
    sa_sync_conn,
):
    conn = sa_sync_conn
    group = _group_of_two(conn)
    store = AuthorGroupingStore(conn)

    assert store.propagate_attributes() == (1, 1)

    row = _attributes(conn, group)
    assert (row.is_corresponding, row.roles, row.evidence, row.in_perimeter) == (
        True,
        ["author", "editor"],
        ["address", "hal_structure", "ror"],
        True,
    )
    assert queued(conn, Queue.CONTRIBUTION_ATTRIBUTES) == set()
    assert store.propagate_attributes() == (0, 0)


def test_une_contribution_hors_file_garde_ses_attributs(sa_sync_conn):
    conn = sa_sync_conn
    group = _group_of_two(conn)
    clear(conn, Queue.CONTRIBUTION_ATTRIBUTES)

    assert AuthorGroupingStore(conn).propagate_attributes() == (0, 0)

    assert _attributes(conn, group).roles is None
