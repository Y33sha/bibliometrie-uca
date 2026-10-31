"""Rattachement des monographies à leur série (`run_link_monographs_to_collections`)."""

import logging

import pytest
from sqlalchemy import text

from pipeline.transformation.publishing.monographs.link_monographs_to_collections import (
    run_link_monographs_to_collections,
)
from pipeline.transformation.publishing.monographs.store import MonographStore
from pipeline.transformation.publishing.serials.delete_empty_serials import delete_empty_serials
from tests.integration.helpers.serials import insert_serial
from tests.integration.helpers.sources import insert_source_record


@pytest.fixture
def repo(sa_sync_conn):
    return MonographStore(sa_sync_conn)


def _volume(conn, repo, title: str, source_id: str) -> int:
    serial_id = insert_serial(conn, title, serial_type="proceedings")
    monograph_id = repo.create_monograph(
        title=title,
        title_normalized=title.lower(),
        proceedings=True,
        year=None,
        isbn=None,
        eisbn=None,
        publisher_id=None,
    )
    insert_source_record(
        conn,
        source="crossref",
        source_id=source_id,
        title="Communication",
        serial_id=serial_id,
        monograph_id=monograph_id,
    )
    return monograph_id


def test_serie_creee_puis_retrouvee(sa_sync_conn, repo):
    first = _volume(sa_sync_conn, repo, "Test Symposium on Series 2022", "series-1")
    second = _volume(sa_sync_conn, repo, "Test Symposium on Series 2023", "series-2")
    logger = logging.getLogger("test_series")

    run_link_monographs_to_collections(sa_sync_conn, logger)

    rows = sa_sync_conn.execute(
        text(
            "SELECT m.id, j.id AS series_id, j.title, j.serial_type::text AS serial_type"
            " FROM monographs m JOIN serials j ON j.id = m.serial_id"
            " WHERE m.id = ANY(:ids) ORDER BY m.id"
        ),
        {"ids": [first, second]},
    ).all()
    assert {(r.title, r.serial_type) for r in rows} == {("Test Symposium on Series", "proceedings")}
    assert rows[0].series_id == rows[1].series_id

    second_run = run_link_monographs_to_collections(sa_sync_conn, logger)
    assert second_run.extras.get("monographs_linked", 0) == 0

    deleted = {j.id for j in delete_empty_serials(sa_sync_conn)}
    assert rows[0].series_id not in deleted
