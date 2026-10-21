"""`scanr_from_hal_sql` : même verdict que `extract_hal_id_from_scanr_id`."""

import pytest
from sqlalchemy import text

from domain.sources.scanr import extract_hal_id_from_scanr_id
from infrastructure.sql_fragments import scanr_from_hal_sql
from tests.integration.helpers.sources import insert_source_record


@pytest.mark.parametrize(
    "source_id",
    [
        "halhal-04501427",
        "haltel-01234567",
        "halHAL-04501427v2",
        "hal-paris",
        "doi10.1/x",
        "nnt2020X",
    ],
)
def test_meme_verdict_en_sql_et_en_python(sa_sync_conn, source_id):
    source_record = insert_source_record(sa_sync_conn, source="scanr", source_id=source_id)
    in_sql = sa_sync_conn.execute(
        text(f"SELECT {scanr_from_hal_sql()} FROM source_records sr WHERE sr.id = :id"),
        {"id": source_record},
    ).scalar_one()
    assert in_sql is (extract_hal_id_from_scanr_id(source_id) is not None)


def test_seulement_scanr(sa_sync_conn):
    source_record = insert_source_record(sa_sync_conn, source="hal", source_id="halhal-04501427")
    assert (
        sa_sync_conn.execute(
            text(f"SELECT {scanr_from_hal_sql()} FROM source_records sr WHERE sr.id = :id"),
            {"id": source_record},
        ).scalar_one()
        is False
    )
