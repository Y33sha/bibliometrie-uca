"""Oneshot `mark_collective_source_contributions` : contributions sources collectives d'après leur nom, décomptes et groupement des auteurs."""

from sqlalchemy import text

from infrastructure.db.queues import Queue
from interfaces.cli.oneshot.mark_collective_source_contributions import (
    _collective_ids,
    mark_collective,
)
from tests.integration.helpers.contributions import upsert_split_contributor_information
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _seed(conn):
    publication = insert_publication(conn)
    source_record = insert_source_record(conn, publication, source="wos", source_id="WOS:1")
    person = insert_source_contribution(
        conn,
        source_record,
        contributor_information_id=upsert_split_contributor_information(conn, "rousseau", "b"),
        author_position=0,
        roles=["author"],
        raw_author_name="ROUSSEAU, B.",
    )
    group = insert_source_contribution(
        conn,
        source_record,
        contributor_information_id=upsert_split_contributor_information(conn, "grp", "face bd"),
        author_position=1,
        roles=["author"],
        raw_author_name="FACE BD Grp",
    )
    clear(conn, Queue.PUBLICATION_CONTRIBUTIONS)
    return publication, source_record, person, group


def test_contains_restreint_l_examen_aux_noms_qui_contiennent_le_texte(sa_sync_conn):
    _, _, person, group = _seed(sa_sync_conn)

    assert _collective_ids(sa_sync_conn, person, group, "grp") == [group]
    assert _collective_ids(sa_sync_conn, person, group, "consortium") == []


def test_une_contribution_source_marquee_change_les_decomptes_et_sa_publication_passe_en_file(
    sa_sync_conn,
):
    conn = sa_sync_conn
    publication, source_record, _, group = _seed(conn)

    mark_collective(conn, [group])

    assert conn.execute(
        text("SELECT collective FROM source_contributions WHERE id = :s"), {"s": group}
    ).scalar_one()
    counts = conn.execute(
        text("SELECT author_count, distinct_author_count FROM source_records WHERE id = :n"),
        {"n": source_record},
    ).one()
    assert tuple(counts) == (1, 1)
    assert queued(conn, Queue.PUBLICATION_CONTRIBUTIONS) == {publication}
