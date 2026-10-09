"""Tests d'intégration du rattachement des monographies à leur série (`run_link_monographs_to_collections` sur la base)."""

import logging

import pytest
from sqlalchemy import text

from application.pipeline.publishers_journals.link_monographs_to_collections import (
    run_link_monographs_to_collections,
)
from infrastructure.pipeline.containers import PgContainerGatewayQueries
from tests.integration.helpers.journals import insert_journal
from tests.integration.helpers.sources import insert_source_publication


@pytest.fixture
def repo(sa_sync_conn):
    return PgContainerGatewayQueries(sa_sync_conn)


def _volume(conn, repo, title: str, source_id: str) -> int:
    journal_id = insert_journal(conn, title, journal_type="proceedings")
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
    insert_source_publication(
        conn,
        source="crossref",
        source_id=source_id,
        title="Communication",
        journal_id=journal_id,
        monograph_id=monograph_id,
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
