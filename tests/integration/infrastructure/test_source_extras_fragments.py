"""Fragments SQL des champs propres aux sources, et leur parité avec les accesseurs du domaine."""

import pytest
from sqlalchemy import text

from domain.source_records.source_extras import SourceExtra, declares_conference
from infrastructure.sql_fragments import (
    declares_conference_sql,
    self_declared_preprint_sql,
    source_extra,
)
from tests.integration.helpers.sources import insert_source_record


def _read(conn, expression, source_record):
    return conn.execute(
        text(f"SELECT {expression} FROM source_records sr WHERE sr.id = :id"), {"id": source_record}
    ).scalar_one()


@pytest.mark.parametrize(
    "source_extras",
    [None, {}, {SourceExtra.CONFERENCE: {"name": "ICRA"}}, {SourceExtra.SERIES: ["x"]}],
)
def test_declares_conference_meme_verdict_en_sql_et_en_python(sa_sync_conn, source_extras):
    source_record = insert_source_record(sa_sync_conn, source_extras=source_extras)
    assert _read(sa_sync_conn, declares_conference_sql(), source_record) is declares_conference(
        source_extras
    )


def test_preprint_declare(sa_sync_conn):
    declarant = insert_source_record(
        sa_sync_conn,
        source_id="c-1",
        source_extras={SourceExtra.RELATION: {"is-preprint-of": [{"id": "10.1/x"}]}},
    )
    other = insert_source_record(sa_sync_conn, source_id="c-2")
    assert _read(sa_sync_conn, self_declared_preprint_sql(), declarant) is True
    assert _read(sa_sync_conn, self_declared_preprint_sql(), other) is False


def test_valeur_texte_d_une_cle(sa_sync_conn):
    source_record = insert_source_record(
        sa_sync_conn, source_extras={SourceExtra.GROUP_TITLE: "oral"}
    )
    assert _read(sa_sync_conn, source_extra(SourceExtra.GROUP_TITLE), source_record) == "oral"
