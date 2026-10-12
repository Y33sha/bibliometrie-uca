"""Intégration : l'upsert normalize écrit `title_normalized` au même mouvement que `title`."""

from sqlalchemy import text

from domain.publications.metadata import normalized_title
from pipeline.ingestion.source_publications import SourcePublicationQueries, SourcePublicationUpsert
from tests.integration.helpers.staging import insert_staging

_Q = SourcePublicationQueries()


def test_upsert_writes_title_normalized(sa_sync_conn):
    conn = sa_sync_conn
    staging_id = insert_staging(conn, "openalex", source_id="W_title_norm")
    raw_title = "Les Cœurs <b>simples</b> &amp;amp; complexes"
    sp_id = _Q.upsert_source_publication(
        conn,
        SourcePublicationUpsert(
            source="openalex",
            source_id="W_title_norm",
            staging_id=staging_id,
            title=raw_title,
            pub_year=2020,
            doc_type="article",
        ),
    )
    stored = conn.execute(
        text("SELECT title, title_normalized FROM source_publications WHERE id = :id"),
        {"id": sp_id},
    ).one()
    assert stored.title == raw_title  # le titre brut est conservé tel quel
    assert stored.title_normalized == normalized_title(raw_title)
    assert stored.title_normalized  # non vide / non NULL
