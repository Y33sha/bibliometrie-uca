"""Suppression des notices parues avant l'année de début du pipeline (`delete_notices_out_of_window`)."""

from functools import partial

from sqlalchemy import text

from interfaces.cli.maintenance.delete_notices_out_of_window import (
    EXEMPT_SOURCES,
    count_targets,
    fetch_cutoff,
)
from pipeline.ingestion.common.source_publications import delete_source_publications_before
from pipeline.transformation.publications.store import PublicationStore
from tests.integration.helpers.config import set_config
from tests.integration.helpers.sources import insert_source_publication
from tests.integration.helpers.staging import insert_staging

_notice = partial(insert_source_publication, title="Titre", keys_dirty=False)


def _publication(conn) -> int:
    return PublicationStore(conn).create(
        title="T",
        title_normalized="t",
        doc_type="article",
        pub_year=2016,
        doi=None,
        oa_status="unknown",
    )


def _notice_staged(conn, publication_id, *, source: str, source_id: str, pub_year: int) -> int:
    staging_id = insert_staging(conn, source, source_id=source_id, processed=True)
    return _notice(
        conn,
        publication_id,
        source=source,
        source_id=source_id,
        pub_year=pub_year,
        staging_id=staging_id,
    )


def _existe(conn, table: str, ident: int) -> bool:
    query = text(f"SELECT count(*) FROM {table} WHERE id = :id")  # noqa: S608
    return conn.execute(query, {"id": ident}).scalar_one() == 1


def test_l_annee_de_debut_est_lue_en_configuration(sa_sync_conn_owner):
    set_config(sa_sync_conn_owner, "pipeline_start_year_full", 2020)
    assert fetch_cutoff(sa_sync_conn_owner) == 2020


def test_la_notice_ancienne_part_avec_sa_ligne_de_staging(sa_sync_conn_owner):
    conn = sa_sync_conn_owner
    ancienne = _notice_staged(
        conn, _publication(conn), source="hal", source_id="hal-1998", pub_year=1998
    )
    staging_id = conn.execute(
        text("SELECT staging_id FROM source_publications WHERE id = :id"), {"id": ancienne}
    ).scalar_one()

    assert count_targets(conn, 2017) == {"hal": 1}
    assert delete_source_publications_before(conn, 2017, exempt_sources=EXEMPT_SOURCES) == (1, 1)
    assert not _existe(conn, "source_publications", ancienne)
    assert not _existe(conn, "staging", staging_id)


def test_la_soeur_dans_la_plage_reste_et_se_reconcilie(sa_sync_conn_owner):
    conn = sa_sync_conn_owner
    publication = _publication(conn)
    _notice_staged(conn, publication, source="openalex", source_id="W2016", pub_year=2016)
    soeur = _notice_staged(conn, publication, source="hal", source_id="hal-2017", pub_year=2017)

    delete_source_publications_before(conn, 2017, exempt_sources=EXEMPT_SOURCES)

    assert _existe(conn, "source_publications", soeur)
    assert conn.execute(
        text("SELECT keys_dirty FROM source_publications WHERE id = :id"), {"id": soeur}
    ).scalar_one()


def test_la_these_ancienne_reste(sa_sync_conn_owner):
    conn = sa_sync_conn_owner
    these = _notice_staged(
        conn, _publication(conn), source="theses", source_id="2005CLF21600", pub_year=2005
    )

    assert count_targets(conn, 2017) == {}
    assert delete_source_publications_before(conn, 2017, exempt_sources=EXEMPT_SOURCES) == (0, 0)
    assert _existe(conn, "source_publications", these)
