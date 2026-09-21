"""Tests d'intégration du rattachement des monographies à leur série (`run_link_monographs_to_collections` sur la base)."""

import logging

import pytest
from sqlalchemy import text

from application.pipeline.publishers_journals.link_monographs_to_collections import (
    run_link_monographs_to_collections,
)
from infrastructure.pipeline.containers import PgContainerGatewayQueries


@pytest.fixture
def repo(sa_sync_conn):
    return PgContainerGatewayQueries(sa_sync_conn)


def _volume(conn, repo, title: str, source_id: str) -> int:
    journal_id = conn.execute(
        text(
            "INSERT INTO journals (title, title_normalized, journal_type)"
            " VALUES (:t, lower(:t), 'proceedings') RETURNING id"
        ),
        {"t": title},
    ).scalar_one()
    monograph_id = repo.create_monograph(
        title=title,
        title_normalized=title.lower(),
        proceedings=True,
        year=None,
        isbn=None,
        eisbn=None,
        publisher_id=None,
        journal_id=journal_id,
    )
    conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, monograph_id, journal_id)"
            " VALUES ('crossref', :sid, 'Communication', :mid, :jid)"
        ),
        {"sid": source_id, "mid": monograph_id, "jid": journal_id},
    )
    return monograph_id


def test_serie_creee_puis_retrouvee(sa_sync_conn, repo):
    first = _volume(sa_sync_conn, repo, "Test Symposium on Series 2022", "series-1")
    second = _volume(sa_sync_conn, repo, "Test Symposium on Series 2023", "series-2")
    logger = logging.getLogger("test_series")

    run_link_monographs_to_collections(logger, monograph_repo=repo)

    rows = sa_sync_conn.execute(
        text(
            "SELECT m.id, j.id AS series_id, j.title, j.journal_type::text AS journal_type"
            " FROM monographs m JOIN journals j ON j.id = m.journal_id"
            " WHERE m.id = ANY(:ids) ORDER BY m.id"
        ),
        {"ids": [first, second]},
    ).all()
    assert {(r.title, r.journal_type) for r in rows} == {
        ("Test Symposium on Series", "proceedings")
    }
    assert rows[0].series_id == rows[1].series_id

    second_run = run_link_monographs_to_collections(logger, monograph_repo=repo)
    assert second_run.extras.get("monographs_linked", 0) == 0

    deleted = {j.id for j in repo.delete_empty_journals()}
    assert rows[0].series_id not in deleted
