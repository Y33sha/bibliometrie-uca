"""Oneshot `mark_collective_source_contributions` : contributions sources collectives d'après leur nom, décomptes et regroupement."""

from sqlalchemy import text

from interfaces.cli.oneshot.mark_collective_source_contributions import (
    _collective_ids,
    mark_collective,
)
from tests.integration.helpers.contributions import upsert_split_contributor_information
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _seed(conn):
    publication = insert_publication(conn)
    conn.execute(
        text("UPDATE publications SET contributions_dirty = false WHERE id = :p"),
        {"p": publication},
    )
    source_record = insert_source_record(conn, publication, source="openalex", source_id="W1")
    person = insert_source_contribution(
        conn,
        source_record,
        contributor_information_id=upsert_split_contributor_information(conn, "rousseau", "b"),
        author_position=0,
        roles=["author"],
        raw_author_name="ROUSSEAU, B.",
    )
    et_al = insert_source_contribution(
        conn,
        source_record,
        contributor_information_id=upsert_split_contributor_information(conn, "al", "et"),
        author_position=1,
        roles=["author"],
        raw_author_name="Et Al.",
    )
    return publication, source_record, person, et_al


def test_contains_restreint_l_examen_aux_noms_qui_contiennent_le_texte(sa_sync_conn):
    _, _, person, et_al = _seed(sa_sync_conn)

    assert _collective_ids(sa_sync_conn, person, et_al, "et al") == [et_al]
    assert _collective_ids(sa_sync_conn, person, et_al, "consortium") == []


def test_une_contribution_source_marquee_change_les_decomptes_et_sa_publication_est_a_regrouper(
    sa_sync_conn,
):
    conn = sa_sync_conn
    publication, source_record, _, et_al = _seed(conn)

    mark_collective(conn, [et_al])

    assert conn.execute(
        text("SELECT collective FROM source_contributions WHERE id = :s"), {"s": et_al}
    ).scalar_one()
    counts = conn.execute(
        text("SELECT author_count, distinct_author_count FROM source_records WHERE id = :n"),
        {"n": source_record},
    ).one()
    assert tuple(counts) == (1, 1)
    assert conn.execute(
        text("SELECT contributions_dirty FROM publications WHERE id = :p"), {"p": publication}
    ).scalar_one()
