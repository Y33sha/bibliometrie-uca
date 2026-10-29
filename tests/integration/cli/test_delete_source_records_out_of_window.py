"""Suppression des enregistrements sources parus avant l'année de début du pipeline (`delete_source_records_out_of_window`)."""

from functools import partial

from sqlalchemy import text

from infrastructure.db.queues import Queue
from interfaces.cli.maintenance.delete_source_records_out_of_window import (
    count_targets,
    fetch_cutoff,
)
from pipeline.ingestion.common.source_records import delete_source_records_before
from pipeline.transformation.publications.store import PublicationStore
from tests.integration.helpers.config import set_config
from tests.integration.helpers.queues import queued
from tests.integration.helpers.sources import insert_source_record
from tests.integration.helpers.staging import insert_staging

_source_record = partial(insert_source_record, title="Titre", marked=False)


def _publication(conn) -> int:
    return PublicationStore(conn).create(
        title="T",
        title_normalized="t",
        doc_type="article",
        publication_year=2016,
        doi=None,
        oa_status="unknown",
    )


def _source_record_staged(
    conn,
    publication_id,
    *,
    source: str,
    source_id: str,
    publication_year: int,
    doc_type: str | None = None,
) -> int:
    staging_id = insert_staging(conn, source, source_id=source_id, processed=True)
    return _source_record(
        conn,
        publication_id,
        source=source,
        source_id=source_id,
        publication_year=publication_year,
        staging_id=staging_id,
        doc_type=doc_type,
    )


def _existe(conn, table: str, ident: int) -> bool:
    query = text(f"SELECT count(*) FROM {table} WHERE id = :id")  # noqa: S608
    return conn.execute(query, {"id": ident}).scalar_one() == 1


def test_l_annee_de_debut_est_lue_en_configuration(sa_sync_conn_owner):
    set_config(sa_sync_conn_owner, "pipeline_start_year_full", 2020)
    assert fetch_cutoff(sa_sync_conn_owner) == 2020


def test_l_enregistrement_source_ancien_part_avec_sa_ligne_de_staging(sa_sync_conn_owner):
    conn = sa_sync_conn_owner
    ancienne = _source_record_staged(
        conn, _publication(conn), source="hal", source_id="hal-1998", publication_year=1998
    )
    staging_id = conn.execute(
        text("SELECT staging_id FROM source_records WHERE id = :id"), {"id": ancienne}
    ).scalar_one()

    assert count_targets(conn, 2017) == {"hal": 1}
    assert delete_source_records_before(conn, 2017) == (1, 1)
    assert not _existe(conn, "source_records", ancienne)
    assert not _existe(conn, "staging", staging_id)


def test_la_soeur_dans_la_plage_reste_et_se_reconcilie(sa_sync_conn_owner):
    conn = sa_sync_conn_owner
    publication = _publication(conn)
    _source_record_staged(
        conn, publication, source="openalex", source_id="W2016", publication_year=2016
    )
    soeur = _source_record_staged(
        conn, publication, source="hal", source_id="hal-2017", publication_year=2017
    )

    delete_source_records_before(conn, 2017)

    assert _existe(conn, "source_records", soeur)
    assert soeur in queued(conn, Queue.SOURCE_RECORD_KEYS)


def test_la_these_soutenue_ancienne_part_la_these_en_cours_reste(sa_sync_conn_owner):
    """Une thèse soutenue avant l'année de début est supprimée. Une thèse en cours reste, quelle que soit son année de première inscription."""
    conn = sa_sync_conn_owner
    soutenue = _source_record_staged(
        conn,
        _publication(conn),
        source="theses",
        source_id="2005CLF21600",
        publication_year=2005,
        doc_type="thesis",
    )
    en_cours = _source_record_staged(
        conn,
        _publication(conn),
        source="theses",
        source_id="s367812",
        publication_year=2012,
        doc_type="ongoing_thesis",
    )

    assert count_targets(conn, 2017) == {"theses": 1}
    assert delete_source_records_before(conn, 2017) == (1, 1)
    assert not _existe(conn, "source_records", soutenue)
    assert _existe(conn, "source_records", en_cours)
